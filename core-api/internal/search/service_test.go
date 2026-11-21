package search

import (
	"context"
	"core-api/internal/broker"
	"core-api/internal/catalog"
	"core-api/internal/models"
	"errors"
	"testing"
)

type fakeInference struct {
	request broker.CandidateSearchRequest
	err     error
}

func (f *fakeInference) SearchCandidates(_ context.Context, r broker.CandidateSearchRequest) (*broker.InferResponse, error) {
	f.request = r
	if f.err != nil {
		return nil, f.err
	}
	return &broker.InferResponse{Status: "success", IndexVersion: "serving-old", Truncated: true, SearchConfig: broker.InferSearchConfig{RetrievalMode: r.RetrievalMode, EffectiveRetrievalMode: r.RetrievalMode}, Data: []broker.InferSearchResult{{VectorID: 4, CatalogProductID: "a", ImageCandidates: []models.ImageCandidate{{VectorID: 4, SimilarityScore: .8}, {VectorID: 5, SimilarityScore: .7}}}}}, nil
}

type fakeCatalog struct {
	filter   catalog.Filter
	version  string
	got      []models.EnrichedResult
	err      error
	eligible []string
}

func (f *fakeCatalog) EligibleProductIDs(_ context.Context, filter catalog.Filter) ([]string, error) {
	f.filter = filter
	return f.eligible, f.err
}
func (f *fakeCatalog) Enrich(_ context.Context, v string, items []models.EnrichedResult) ([]models.EnrichedResult, error) {
	f.version = v
	f.got = items
	return items, f.err
}
func (f *fakeCatalog) SearchProducts(_ context.Context, _ []models.EnrichedResult, filter catalog.Filter) ([]catalog.Product, error) {
	return []catalog.Product{{ID: "a"}, {ID: "b"}, {ID: "c"}}, f.err
}

func TestCandidatesPinVersionAndKeepEmptyEligibility(t *testing.T) {
	infer := &fakeInference{}
	repo := &fakeCatalog{}
	_, items, err := NewService(infer, repo).Candidates(context.Background(), "boots", broker.SearchConfig{MRLDimension: 512, SearchMode: "adaptive", RetrievalMode: "hybrid"}, catalog.Filter{Category: "shoes"})
	if err != nil {
		t.Fatal(err)
	}
	if infer.request.EligibleProductIDs == nil || len(*infer.request.EligibleProductIDs) != 0 {
		t.Fatal("empty catalog became unrestricted")
	}
	if repo.version != "serving-old" || len(items) != 1 || len(repo.got[0].ImageCandidates) != 2 || repo.filter.Category != "shoes" {
		t.Fatalf("snapshot/filter/alternates lost: %+v", repo)
	}
}

func TestProductsPageCompleteHydratedPool(t *testing.T) {
	repo := &fakeCatalog{eligible: []string{"a", "b", "c"}}
	svc := NewService(&fakeInference{}, repo)
	items, total, metadata, err := svc.Products(context.Background(), catalog.Filter{Q: "boots", Page: 2, Limit: 2, Sort: "price_asc"}, broker.SearchConfig{RetrievalMode: "hybrid"})
	if err != nil {
		t.Fatal(err)
	}
	if total != 3 || len(items) != 1 || items[0].ID != "c" || !metadata.Truncated || metadata.IndexVersion != "serving-old" {
		t.Fatalf("pool pagination incorrect: %v %d %+v", items, total, metadata)
	}
	items, total, _, err = svc.Products(context.Background(), catalog.Filter{Q: "boots", Page: 10, Limit: 2}, broker.SearchConfig{RetrievalMode: "dense"})
	if err != nil || len(items) != 0 || total != 3 {
		t.Fatalf("out-of-range page incorrect: %v %d %v", items, total, err)
	}
}

func TestCatalogFailureDoesNotSearchUnfiltered(t *testing.T) {
	infer := &fakeInference{}
	repo := &fakeCatalog{err: errors.New("database down")}
	_, _, err := NewService(infer, repo).Candidates(context.Background(), "boots", broker.SearchConfig{}, catalog.Filter{})
	if err == nil || infer.request.Query != "" {
		t.Fatal("catalog error fell through to unrestricted retrieval")
	}
}
