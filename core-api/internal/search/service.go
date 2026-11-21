package search

import (
	"context"
	"core-api/internal/broker"
	"core-api/internal/catalog"
	"core-api/internal/models"
	"errors"
	"time"
)

type Inference interface {
	SearchCandidates(context.Context, broker.CandidateSearchRequest) (*broker.InferResponse, error)
}

type Catalog interface {
	EligibleProductIDs(context.Context, catalog.Filter) ([]string, error)
	Enrich(context.Context, string, []models.EnrichedResult) ([]models.EnrichedResult, error)
	SearchProducts(context.Context, []models.EnrichedResult, catalog.Filter) ([]catalog.Product, error)
}

// Service keeps text retrieval, eligibility and versioned hydration shared by
// the legacy search endpoint and the paginated catalog endpoint.
type Service struct {
	infer   Inference
	catalog Catalog
}

func NewService(infer Inference, repo Catalog) *Service { return &Service{infer: infer, catalog: repo} }
func (s *Service) WithCatalog(repo Catalog) *Service    { s.catalog = repo; return s }

func (s *Service) Candidates(ctx context.Context, query string, cfg broker.SearchConfig, filter catalog.Filter) (*broker.InferResponse, []models.EnrichedResult, error) {
	request := broker.CandidateSearchRequest{Query: query, MRLDimension: cfg.MRLDimension, SearchMode: cfg.SearchMode, RetrievalMode: cfg.RetrievalMode}
	catalogTime := time.Duration(0)
	if s.catalog != nil {
		started := time.Now()
		ids, err := s.catalog.EligibleProductIDs(ctx, filter)
		catalogTime += time.Since(started)
		if err != nil {
			return nil, nil, err
		}
		if ids == nil {
			ids = []string{}
		}
		request.EligibleProductIDs = &ids
	}
	infer, err := s.infer.SearchCandidates(ctx, request)
	if err != nil {
		return nil, nil, err
	}
	items := make([]models.EnrichedResult, 0, len(infer.Data))
	for _, item := range infer.Data {
		items = append(items, models.EnrichedResult{VectorID: item.VectorID, ProductID: item.ProductID, CatalogProductID: item.CatalogProductID, SimilarityScore: item.SimilarityScore, Caption: item.Caption, RankScore: item.RankScore, ImageCandidates: item.ImageCandidates})
	}
	if s.catalog != nil {
		started := time.Now()
		items, err = s.catalog.Enrich(ctx, infer.IndexVersion, items)
		catalogTime += time.Since(started)
		if err != nil {
			return nil, nil, err
		}
	}
	infer.CatalogMs = float64(catalogTime) / float64(time.Millisecond)
	return infer, items, nil
}

func Metadata(infer *broker.InferResponse) models.SearchMetadata {
	cfg := infer.SearchConfig
	return models.SearchMetadata{IndexVersion: infer.IndexVersion, RetrievalMode: cfg.RetrievalMode, EffectiveRetrievalMode: cfg.EffectiveRetrievalMode, LexicalAvailable: cfg.LexicalAvailable, FallbackReason: cfg.FallbackReason, Truncated: infer.Truncated}
}

func (s *Service) Products(ctx context.Context, filter catalog.Filter, cfg broker.SearchConfig) ([]catalog.Product, int, models.SearchMetadata, error) {
	if s.catalog == nil {
		return nil, 0, models.SearchMetadata{}, errors.New("catalog is not configured")
	}
	infer, items, err := s.Candidates(ctx, filter.Q, cfg, filter)
	if err != nil {
		return nil, 0, models.SearchMetadata{}, err
	}
	products, err := s.catalog.SearchProducts(ctx, items, filter)
	if err != nil {
		return nil, 0, models.SearchMetadata{}, err
	}
	total := len(products)
	start := (filter.Page - 1) * filter.Limit
	if start >= total {
		return []catalog.Product{}, total, Metadata(infer), nil
	}
	end := start + filter.Limit
	if end > total {
		end = total
	}
	return products[start:end], total, Metadata(infer), nil
}
