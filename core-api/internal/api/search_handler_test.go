package api

import (
	"core-api/internal/broker"
	"encoding/json"
	"fmt"
	"github.com/gin-gonic/gin"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync"
	"testing"
	"time"
)

func TestGatewayContract(t *testing.T) {
	gin.SetMode(gin.TestMode)
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		r.ParseMultipartForm(1024)
		switch r.FormValue("query") {
		case "bad":
			http.Error(w, `{"detail":"Unsupported dim"}`, 400)
			return
		case "slow":
			time.Sleep(80 * time.Millisecond)
		}
		fmt.Fprintf(w, `{"status":"success","data":[{"vector_id":0,"product_id":"3238.jpg","similarity_score":0.8}],"search_config":{"requested_dim":64,"search_mode":"direct","stage1_dim":64},"timing":{"worker_total_ms":1}}`)
	}))
	defer upstream.Close()
	router := gin.New()
	NewSearchHandler(broker.NewInferClient(upstream.URL, 40*time.Millisecond)).RegisterRoutes(router.Group("/api"))
	request := func(query string) *httptest.ResponseRecorder {
		form := url.Values{"query": {query}, "mrl_dimension": {"64"}, "search_mode": {"direct"}}
		req := httptest.NewRequest("POST", "/api/search/text", strings.NewReader(form.Encode()))
		req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
		out := httptest.NewRecorder()
		router.ServeHTTP(out, req)
		return out
	}
	for _, tc := range []struct {
		q    string
		code int
	}{{"bad", 400}, {"slow", 504}, {"ok", 200}} {
		out := request(tc.q)
		if out.Code != tc.code {
			t.Fatalf("%s: %d %s", tc.q, out.Code, out.Body.String())
		}
	}
	var wg sync.WaitGroup
	for i := 0; i < 10; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			out := request("ok")
			if out.Code != 200 {
				t.Errorf("concurrent status %d", out.Code)
				return
			}
			var p struct {
				Data []struct {
					ProductID string `json:"product_id"`
				}
			}
			json.Unmarshal(out.Body.Bytes(), &p)
			if len(p.Data) != 1 || p.Data[0].ProductID != "3238.jpg" {
				t.Error("image mapping lost")
			}
		}()
	}
	wg.Wait()
}
