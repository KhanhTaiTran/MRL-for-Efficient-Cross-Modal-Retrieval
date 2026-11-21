package broker

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestCandidateJSONContract(t *testing.T) {
	for _, restricted := range []bool{false, true} {
		t.Run(map[bool]string{false: "unrestricted", true: "empty eligibility"}[restricted], func(t *testing.T) {
			upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.URL.Path != "/infer/search/candidates" || r.Header.Get("Content-Type") != "application/json" {
					t.Error("candidate endpoint or content type lost")
				}
				var body map[string]json.RawMessage
				if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
					t.Error(err)
				}
				eligible, exists := body["eligible_product_ids"]
				if exists != restricted || (restricted && string(eligible) != "[]") {
					t.Errorf("eligibility widened: %s", eligible)
				}
				w.Header().Set("Content-Type", "application/json")
				w.Write([]byte(`{"status":"success","index_version":"v1","truncated":true,"search_config":{"retrieval_mode":"hybrid","effective_retrieval_mode":"dense","fallback_reason":"lexical_missing"},"data":[{"catalog_product_id":"p","vector_id":1,"similarity_score":0.4,"rank_score":0.02,"image_candidates":[{"vector_id":2,"similarity_score":0.3}]}]}`))
			}))
			defer upstream.Close()
			request := CandidateSearchRequest{Query: "red dress", MRLDimension: 512, SearchMode: "adaptive", RetrievalMode: "hybrid"}
			if restricted {
				ids := []string{}
				request.EligibleProductIDs = &ids
			}
			response, err := NewInferClient(upstream.URL, time.Second).SearchCandidates(context.Background(), request)
			if err != nil {
				t.Fatal(err)
			}
			if !response.Truncated || response.SearchConfig.EffectiveRetrievalMode != "dense" || response.SearchConfig.FallbackReason != "lexical_missing" || len(response.Data) != 1 || response.Data[0].RankScore == nil || len(response.Data[0].ImageCandidates) != 1 {
				t.Fatalf("candidate response fields lost: %+v", response)
			}
		})
	}
}

func TestCandidateUpstreamError(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { http.Error(w, `{"detail":"bad dimension"}`, 400) }))
	defer upstream.Close()
	_, err := NewInferClient(upstream.URL, time.Second).SearchCandidates(context.Background(), CandidateSearchRequest{})
	if err == nil || ErrorStatus(err) != 400 {
		t.Fatalf("upstream status lost: %v", err)
	}
}
