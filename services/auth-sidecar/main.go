// Package main implements a production-ready authentication sidecar
// for NukeLab server containers.
//
// It validates short-lived, server-scoped JWT access tokens signed by
// the backend using RS256 asymmetric cryptography.
//
// Architecture:
//   - Backend holds private key, signs tokens
//   - This sidecar holds public key, validates tokens locally
//   - No network calls to backend per request
//   - Tokens are scoped to a specific server and user
//
// Architecture:
//   - nginx receives HTTP/WebSocket requests
//   - nginx auth_request calls this sidecar for token validation
//   - If valid, nginx proxies to ttyd (web terminal)
//   - If invalid, nginx returns 401
//
// Security features:
//   - Asymmetric key validation (RS256)
//   - Server ID scoping (token aud claim must match container)
//   - Token expiry validation
//   - Rate limiting on validation requests
//   - No exposure of main JWT secret
//   - Minimal attack surface (single binary, no shell)
package main

import (
	"crypto/rsa"
	"crypto/x509"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"io/ioutil"
	"log"
	"net"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/gorilla/mux"
)

// Config holds the sidecar configuration loaded from environment variables.
type Config struct {
	// Server identification
	ServerID string `json:"server_id"`

	// Authentication settings
	AuthEnabled     bool   `json:"auth_enabled"`
	PublicKeyPath   string `json:"public_key_path"`
	Algorithm       string `json:"algorithm"`
	TokenHeader     string `json:"token_header"`
	TokenCookie     string `json:"token_cookie"`
	TokenQueryParam string `json:"token_query_param"`

	// HTTP server settings
	ListenAddr      string `json:"listen_addr"`
	ReadTimeout     int    `json:"read_timeout"`
	WriteTimeout    int    `json:"write_timeout"`
	MaxHeaderBytes  int    `json:"max_header_bytes"`

	// Rate limiting
	RateLimitEnabled   bool `json:"rate_limit_enabled"`
	RateLimitRequests  int  `json:"rate_limit_requests"`
	RateLimitWindow    int  `json:"rate_limit_window"`

	// Logging
	LogLevel string `json:"log_level"`
}

// ValidationResult represents the outcome of token validation.
type ValidationResult struct {
	Valid      bool   `json:"valid"`
	UserID     string `json:"user_id,omitempty"`
	ServerID   string `json:"server_id,omitempty"`
	TokenType  string `json:"token_type,omitempty"`
	Error      string `json:"error,omitempty"`
	Expiry     int64  `json:"exp,omitempty"`
}

// AuthSidecar is the main authentication sidecar instance.
type AuthSidecar struct {
	config     *Config
	publicKey  *rsa.PublicKey
	rateLimiter *RateLimiter
	logger     *log.Logger
}

// RateLimiter implements a simple token bucket rate limiter per IP.
type RateLimiter struct {
	mu       sync.RWMutex
	buckets  map[string]*bucket
	requests int
	window   time.Duration
}

type bucket struct {
	tokens    int
	lastReset time.Time
}

func NewRateLimiter(requests int, window time.Duration) *RateLimiter {
	return &RateLimiter{
		buckets:  make(map[string]*bucket),
		requests: requests,
		window:   window,
	}
}

func (rl *RateLimiter) Allow(ip string) bool {
	rl.mu.Lock()
	defer rl.mu.Unlock()

	b, exists := rl.buckets[ip]
	if !exists {
		b = &bucket{tokens: rl.requests, lastReset: time.Now()}
		rl.buckets[ip] = b
	}

	// Reset bucket if window has passed
	if time.Since(b.lastReset) > rl.window {
		b.tokens = rl.requests
		b.lastReset = time.Now()
	}

	if b.tokens <= 0 {
		return false
	}

	b.tokens--
	return true
}

// LoadConfig loads configuration from environment variables.
func LoadConfig() *Config {
	cfg := &Config{
		ServerID:        getEnv("NUKELAB_AUTH_SERVER_ID", ""),
		AuthEnabled:     getEnvBool("NUKELAB_AUTH_ENABLED", true),
		PublicKeyPath:   getEnv("NUKELAB_AUTH_PUBLIC_KEY_PATH", "/etc/nukelab/auth/public.pem"),
		Algorithm:       getEnv("NUKELAB_AUTH_ALGORITHM", "RS256"),
		TokenHeader:     getEnv("NUKELAB_AUTH_TOKEN_HEADER", "Authorization"),
		TokenCookie:     getEnv("NUKELAB_AUTH_TOKEN_COOKIE", "nukelab_server_token"),
		TokenQueryParam: getEnv("NUKELAB_AUTH_TOKEN_QUERY_PARAM", "access_token"),
		ListenAddr:      getEnv("NUKELAB_AUTH_LISTEN_ADDR", ":8080"),
		ReadTimeout:     getEnvInt("NUKELAB_AUTH_READ_TIMEOUT", 5),
		WriteTimeout:    getEnvInt("NUKELAB_AUTH_WRITE_TIMEOUT", 5),
		MaxHeaderBytes:  getEnvInt("NUKELAB_AUTH_MAX_HEADER_BYTES", 16384),
		RateLimitEnabled: getEnvBool("NUKELAB_AUTH_RATE_LIMIT_ENABLED", true),
		RateLimitRequests: getEnvInt("NUKELAB_AUTH_RATE_LIMIT_REQUESTS", 100),
		RateLimitWindow:   getEnvInt("NUKELAB_AUTH_RATE_LIMIT_WINDOW", 60),
		LogLevel:          getEnv("NUKELAB_AUTH_LOG_LEVEL", "info"),
	}

	return cfg
}

// LoadPublicKey loads and parses the RSA public key from file.
func LoadPublicKey(path string) (*rsa.PublicKey, error) {
	data, err := ioutil.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("failed to read public key file: %w", err)
	}

	block, _ := pem.Decode(data)
	if block == nil {
		return nil, fmt.Errorf("failed to decode PEM block")
	}

	key, err := x509.ParsePKIXPublicKey(block.Bytes)
	if err != nil {
		// Try PKCS1 format
		key, err = x509.ParsePKCS1PublicKey(block.Bytes)
		if err != nil {
			return nil, fmt.Errorf("failed to parse public key: %w", err)
		}
	}

	rsaKey, ok := key.(*rsa.PublicKey)
	if !ok {
		return nil, fmt.Errorf("key is not an RSA public key")
	}

	return rsaKey, nil
}

// NewAuthSidecar creates a new authentication sidecar instance.
func NewAuthSidecar(cfg *Config) (*AuthSidecar, error) {
	logger := log.New(os.Stdout, "[auth-sidecar] ", log.LstdFlags|log.Lmicroseconds)

	var publicKey *rsa.PublicKey
	var err error

	if cfg.AuthEnabled {
		publicKey, err = LoadPublicKey(cfg.PublicKeyPath)
		if err != nil {
			return nil, fmt.Errorf("failed to load public key: %w", err)
		}
		logger.Printf("INFO: Loaded public key from %s", cfg.PublicKeyPath)
	}

	var rateLimiter *RateLimiter
	if cfg.RateLimitEnabled {
		rateLimiter = NewRateLimiter(
			cfg.RateLimitRequests,
			time.Duration(cfg.RateLimitWindow)*time.Second,
		)
		logger.Printf("INFO: Rate limiting enabled: %d requests per %d seconds",
			cfg.RateLimitRequests, cfg.RateLimitWindow)
	}

	return &AuthSidecar{
		config:      cfg,
		publicKey:   publicKey,
		rateLimiter: rateLimiter,
		logger:      logger,
	}, nil
}

// extractToken extracts the JWT token from the request.
// Priority: 1. Query param (current request), 2. Query param (from X-Original-Uri header for nginx auth_request),
// 3. Cookie, 4. Authorization header
func (a *AuthSidecar) extractToken(r *http.Request) string {
	// 1. Check query parameter (for WebSocket connections)
	if token := r.URL.Query().Get(a.config.TokenQueryParam); token != "" {
		return token
	}

	// 2. Check X-Original-Uri header (set by nginx auth_request)
	// This contains the original request URI with query parameters
	if originalUri := r.Header.Get("X-Original-Uri"); originalUri != "" {
		if idx := strings.Index(originalUri, "?"); idx != -1 {
			queryString := originalUri[idx+1:]
			// Parse query string manually
			pairs := strings.Split(queryString, "&")
			for _, pair := range pairs {
				if idx := strings.Index(pair, "="); idx != -1 {
					key := pair[:idx]
					value := pair[idx+1:]
					if key == a.config.TokenQueryParam {
						return value
					}
				}
			}
		}
	}

	// 3. Check cookie
	if cookie, err := r.Cookie(a.config.TokenCookie); err == nil {
		return cookie.Value
	}

	// 4. Check Authorization header
	auth := r.Header.Get(a.config.TokenHeader)
	if auth != "" {
		// Handle "Bearer <token>" format
		if strings.HasPrefix(strings.ToLower(auth), "bearer ") {
			return auth[7:]
		}
		return auth
	}

	return ""
}

// validateToken validates a JWT token and returns the result.
func (a *AuthSidecar) validateToken(tokenString string) (*ValidationResult, error) {
	if !a.config.AuthEnabled {
		return &ValidationResult{Valid: true, Error: "auth_disabled"}, nil
	}

	token, err := jwt.Parse(tokenString, func(token *jwt.Token) (interface{}, error) {
		// Validate algorithm
		if token.Method.Alg() != a.config.Algorithm {
			return nil, fmt.Errorf("unexpected signing method: %v", token.Header["alg"])
		}
		return a.publicKey, nil
	}, jwt.WithValidMethods([]string{a.config.Algorithm}))

	if err != nil {
		return &ValidationResult{Valid: false, Error: err.Error()}, nil
	}

	if !token.Valid {
		return &ValidationResult{Valid: false, Error: "invalid_token"}, nil
	}

	claims, ok := token.Claims.(jwt.MapClaims)
	if !ok {
		return &ValidationResult{Valid: false, Error: "invalid_claims"}, nil
	}

	// Validate server ID (audience claim)
	aud, ok := claims["aud"].(string)
	if !ok || aud == "" {
		return &ValidationResult{Valid: false, Error: "missing_audience"}, nil
	}

	if aud != a.config.ServerID {
		return &ValidationResult{
			Valid:    false,
			Error:    "server_mismatch",
			ServerID: aud,
		}, nil
	}

	// Extract user ID (subject claim)
	sub, ok := claims["sub"].(string)
	if !ok || sub == "" {
		return &ValidationResult{Valid: false, Error: "missing_subject"}, nil
	}

	// Extract token type
	tokenType, _ := claims["type"].(string)
	if tokenType == "" {
		tokenType = "session"
	}

	// Extract expiry
	var expiry int64
	if exp, ok := claims["exp"].(float64); ok {
		expiry = int64(exp)
	}

	return &ValidationResult{
		Valid:     true,
		UserID:    sub,
		ServerID:  aud,
		TokenType: tokenType,
		Expiry:    expiry,
	}, nil
}

// HealthHandler handles health check requests.
func (a *AuthSidecar) HealthHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(map[string]interface{}{
		"status": "healthy",
		"auth_enabled": a.config.AuthEnabled,
		"server_id": a.config.ServerID,
	})
}

// ValidateHandler handles token validation requests.
func (a *AuthSidecar) ValidateHandler(w http.ResponseWriter, r *http.Request) {
	// Rate limiting
	if a.rateLimiter != nil {
		clientIP, _, _ := net.SplitHostPort(r.RemoteAddr)
		if clientIP == "" {
			clientIP = r.RemoteAddr
		}
		if !a.rateLimiter.Allow(clientIP) {
			a.logger.Printf("WARN: Rate limit exceeded for IP: %s", clientIP)
			http.Error(w, `{"error":"rate_limit_exceeded"}`, http.StatusTooManyRequests)
			return
		}
	}

	// Extract token
	token := a.extractToken(r)
	if token == "" {
		if a.config.AuthEnabled {
			http.Error(w, `{"error":"missing_token"}`, http.StatusUnauthorized)
			return
		}
		// Auth disabled, allow through
		w.Header().Set("X-Auth-Status", "disabled")
		w.WriteHeader(http.StatusOK)
		return
	}

	// Validate token
	result, err := a.validateToken(token)
	if err != nil {
		a.logger.Printf("ERROR: Token validation error: %v", err)
		http.Error(w, `{"error":"validation_error"}`, http.StatusInternalServerError)
		return
	}

	if !result.Valid {
		a.logger.Printf("WARN: Invalid token: %s", result.Error)
		w.Header().Set("X-Auth-Error", result.Error)
		http.Error(w, fmt.Sprintf(`{"error":"%s"}`, result.Error), http.StatusUnauthorized)
		return
	}

	// Success - set headers for downstream services
	w.Header().Set("X-User-Id", result.UserID)
	w.Header().Set("X-Server-Id", result.ServerID)
	w.Header().Set("X-Token-Type", result.TokenType)
	w.Header().Set("X-Auth-Status", "valid")
	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(result)
}

// AuthRequestHandler handles nginx auth_request subrequests.
func (a *AuthSidecar) AuthRequestHandler(w http.ResponseWriter, r *http.Request) {
	// Rate limiting
	if a.rateLimiter != nil {
		clientIP, _, _ := net.SplitHostPort(r.RemoteAddr)
		if clientIP == "" {
			clientIP = r.RemoteAddr
		}
		if !a.rateLimiter.Allow(clientIP) {
			a.logger.Printf("WARN: Rate limit exceeded for IP: %s", clientIP)
			w.WriteHeader(http.StatusTooManyRequests)
			return
		}
	}

	// Extract token
	token := a.extractToken(r)
	if token == "" {
		if a.config.AuthEnabled {
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		// Auth disabled, allow through
		w.Header().Set("X-User-Id", "anonymous")
		w.WriteHeader(http.StatusOK)
		return
	}

	// Validate token
	result, err := a.validateToken(token)
	if err != nil {
		a.logger.Printf("ERROR: Token validation error: %v", err)
		w.WriteHeader(http.StatusInternalServerError)
		return
	}

	if !result.Valid {
		a.logger.Printf("WARN: Invalid token: %s", result.Error)
		w.WriteHeader(http.StatusUnauthorized)
		return
	}

	// Success - set headers for nginx to pass to backend
	w.Header().Set("X-User-Id", result.UserID)
	w.Header().Set("X-Server-Id", result.ServerID)
	w.Header().Set("X-Token-Type", result.TokenType)
	w.WriteHeader(http.StatusOK)
}

// SetupRoutes configures the HTTP router.
func (a *AuthSidecar) SetupRoutes() *mux.Router {
	r := mux.NewRouter()

	// Health check
	r.HandleFunc("/health", a.HealthHandler).Methods("GET")

	// Validation endpoint (returns JSON)
	r.HandleFunc("/validate", a.ValidateHandler).Methods("GET", "POST")

	// Nginx auth_request endpoint (returns status only)
	r.HandleFunc("/auth", a.AuthRequestHandler).Methods("GET")

	// Metrics endpoint (basic)
	r.HandleFunc("/metrics", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"auth_enabled": a.config.AuthEnabled,
			"server_id":    a.config.ServerID,
			"algorithm":    a.config.Algorithm,
		})
	}).Methods("GET")

	return r
}

// Run starts the authentication sidecar HTTP server.
func (a *AuthSidecar) Run() error {
	router := a.SetupRoutes()

	server := &http.Server{
		Addr:           a.config.ListenAddr,
		Handler:        router,
		ReadTimeout:    time.Duration(a.config.ReadTimeout) * time.Second,
		WriteTimeout:   time.Duration(a.config.WriteTimeout) * time.Second,
		MaxHeaderBytes: a.config.MaxHeaderBytes,
	}

	a.logger.Printf("INFO: Starting auth sidecar on %s", a.config.ListenAddr)
	a.logger.Printf("INFO: Server ID: %s", a.config.ServerID)
	a.logger.Printf("INFO: Auth enabled: %v", a.config.AuthEnabled)

	return server.ListenAndServe()
}

// Helper functions
func getEnv(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}

func getEnvBool(key string, defaultValue bool) bool {
	value := os.Getenv(key)
	switch strings.ToLower(value) {
	case "true", "1", "yes", "on":
		return true
	case "false", "0", "no", "off":
		return false
	default:
		return defaultValue
	}
}

func getEnvInt(key string, defaultValue int) int {
	value := os.Getenv(key)
	if value == "" {
		return defaultValue
	}
	var result int
	fmt.Sscanf(value, "%d", &result)
	if result == 0 {
		return defaultValue
	}
	return result
}

func main() {
	cfg := LoadConfig()

	// Validate required config
	if cfg.ServerID == "" {
		log.Fatal("NUKELAB_AUTH_SERVER_ID is required")
	}

	sidecar, err := NewAuthSidecar(cfg)
	if err != nil {
		log.Fatalf("Failed to create auth sidecar: %v", err)
	}

	if err := sidecar.Run(); err != nil {
		log.Fatalf("Auth sidecar failed: %v", err)
	}
}
