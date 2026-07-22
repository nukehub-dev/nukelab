// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

package main

import (
	"encoding/json"
	"io"
	"log"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
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
