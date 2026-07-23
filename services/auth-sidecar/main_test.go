// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

package main

import (
	"crypto/rand"
	"crypto/rsa"
	"encoding/json"
	"io"
	"log"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

func newTestSidecar(authEnabled bool) *AuthSidecar {
	return &AuthSidecar{
		config: &Config{
			ServerID:    "test-server",
			AuthEnabled: authEnabled,
		},
		logger: log.New(io.Discard, "", 0),
	}
}

func TestRecordActivityUpdatesTimestamp(t *testing.T) {
	a := newTestSidecar(false)
	if got := a.lastActivity.Load(); got != 0 {
		t.Fatalf("expected initial last_activity 0, got %d", got)
	}
	before := time.Now().Unix()
	a.recordActivity()
	if got := a.lastActivity.Load(); got < before {
		t.Fatalf("expected last_activity >= %d, got %d", before, got)
	}
}

func TestActivityHandlerReportsLastActivity(t *testing.T) {
	a := newTestSidecar(false)
	a.lastActivity.Store(12345)

	req := httptest.NewRequest(http.MethodGet, "/activity", nil)
	rec := httptest.NewRecorder()
	a.ActivityHandler(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
	var body map[string]interface{}
	if err := json.NewDecoder(rec.Body).Decode(&body); err != nil {
		t.Fatalf("invalid JSON: %v", err)
	}
	if body["server_id"] != "test-server" {
		t.Fatalf("unexpected server_id: %v", body["server_id"])
	}
	if body["last_activity"] != float64(12345) {
		t.Fatalf("unexpected last_activity: %v", body["last_activity"])
	}
}

func TestAuthRequestHandlerRecordsActivityWhenAuthDisabled(t *testing.T) {
	a := newTestSidecar(false)

	req := httptest.NewRequest(http.MethodGet, "/auth", nil)
	rec := httptest.NewRecorder()
	a.AuthRequestHandler(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
	if a.lastActivity.Load() == 0 {
		t.Fatal("expected pass-through request to record activity")
	}
}

func TestHealthHandlerDoesNotRecordActivity(t *testing.T) {
	a := newTestSidecar(false)

	req := httptest.NewRequest(http.MethodGet, "/health", nil)
	rec := httptest.NewRecorder()
	a.HealthHandler(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
	if a.lastActivity.Load() != 0 {
		t.Fatal("health probes must not count as user activity")
	}
}

func signToken(t *testing.T, key *rsa.PrivateKey, aud string, exp time.Time) string {
	t.Helper()
	claims := jwt.MapClaims{
		"sub":  "user-1",
		"aud":  aud,
		"exp":  exp.Unix(),
		"iat":  time.Now().Add(-time.Hour).Unix(),
		"jti":  "token-1",
		"type": "session",
	}
	token, err := jwt.NewWithClaims(jwt.SigningMethodRS256, claims).SignedString(key)
	if err != nil {
		t.Fatalf("failed to sign token: %v", err)
	}
	return token
}

func newAuthTestSidecar(t *testing.T) (*AuthSidecar, *rsa.PrivateKey) {
	t.Helper()
	key, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatalf("failed to generate key: %v", err)
	}
	a := &AuthSidecar{
		config: &Config{
			ServerID:    "test-server",
			AuthEnabled: true,
			Algorithm:   "RS256",
			TokenCookie: "nukelab_server_token",
		},
		publicKey: &key.PublicKey,
		logger:    log.New(io.Discard, "", 0),
	}
	return a, key
}

func authRequestWithCookie(token string) (*http.Request, *httptest.ResponseRecorder) {
	req := httptest.NewRequest(http.MethodGet, "/auth", nil)
	if token != "" {
		req.AddCookie(&http.Cookie{Name: "nukelab_server_token", Value: token})
	}
	return req, httptest.NewRecorder()
}

func TestExpiredAuthenticTokenRecordsActivityButIsRejected(t *testing.T) {
	a, key := newAuthTestSidecar(t)
	token := signToken(t, key, "test-server", time.Now().Add(-time.Minute))

	req, rec := authRequestWithCookie(token)
	a.AuthRequestHandler(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("expired token must still be rejected, got %d", rec.Code)
	}
	if a.lastActivity.Load() == 0 {
		t.Fatal("expired-but-authentic token should count as activity")
	}
}

func TestExpiredTokenWithWrongAudienceRecordsNoActivity(t *testing.T) {
	a, key := newAuthTestSidecar(t)
	token := signToken(t, key, "other-server", time.Now().Add(-time.Minute))

	req, rec := authRequestWithCookie(token)
	a.AuthRequestHandler(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", rec.Code)
	}
	if a.lastActivity.Load() != 0 {
		t.Fatal("token for another server must not count as activity")
	}
}

func TestGarbageTokenRecordsNoActivity(t *testing.T) {
	a, _ := newAuthTestSidecar(t)

	req, rec := authRequestWithCookie("not-a-jwt")
	a.AuthRequestHandler(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", rec.Code)
	}
	if a.lastActivity.Load() != 0 {
		t.Fatal("forged tokens must not count as activity")
	}
}

func TestExpiredTokenSignedByWrongKeyRecordsNoActivity(t *testing.T) {
	a, _ := newAuthTestSidecar(t)
	otherKey, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatalf("failed to generate key: %v", err)
	}
	token := signToken(t, otherKey, "test-server", time.Now().Add(-time.Minute))

	req, rec := authRequestWithCookie(token)
	a.AuthRequestHandler(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", rec.Code)
	}
	if a.lastActivity.Load() != 0 {
		t.Fatal("token signed by a foreign key must not count as activity")
	}
}

func TestValidTokenRecordsActivity(t *testing.T) {
	a, key := newAuthTestSidecar(t)
	token := signToken(t, key, "test-server", time.Now().Add(time.Hour))

	req, rec := authRequestWithCookie(token)
	a.AuthRequestHandler(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
	if a.lastActivity.Load() == 0 {
		t.Fatal("valid token should count as activity")
	}
}
