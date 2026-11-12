package api

import (
	"context"
	"core-api/internal/broker"
	"core-api/internal/catalog"
	"core-api/internal/models"
	searchservice "core-api/internal/search"
	"encoding/json"
	"fmt"
	"github.com/gin-gonic/gin"
	"net/http"
	"net/http/httptest"
	"net/url"
	"sort"
	"strings"
	"testing"
	"time"
)

type productSearchFixture struct {
	browsed bool
	filter  catalog.Filter
	version string
}

func (f *productSearchFixture) List(_ context.Context, filter catalog.Filter) ([]catalog.Product, int, error) {
	f.browsed = true
	f.filter = filter
	return []catalog.Product{{ID: "browse"}}, 1, nil
}
func (f *productSearchFixture) Categories(context.Context) ([]string, error) { return []string{}, nil }
func (f *productSearchFixture) Get(context.Context, string) (catalog.Product, error) {
	return catalog.Product{}, nil
}
func (f *productSearchFixture) EligibleProductIDs(_ context.Context, filter catalog.Filter) ([]string, error) {
	f.filter = filter
	return []string{"a", "b", "c"}, nil
}
func (f *productSearchFixture) Enrich(_ context.Context, version string, items []models.EnrichedResult) ([]models.EnrichedResult, error) {
	f.version = version
	return items, nil
}
func (f *productSearchFixture) SearchProducts(_ context.Context, items []models.EnrichedResult, filter catalog.Filter) ([]catalog.Product, error) {
	products := make([]catalog.Product, 0, len(items))
	for _, item := range items {
		products = append(products, catalog.Product{ID: item.CatalogProductID, Price: map[string]float64{"a": 30, "b": 10, "c": 20}[item.CatalogProductID]})
	}
	if filter.Sort == "price_asc" {
		sort.Slice(products, func(i, j int) bool { return products[i].Price < products[j].Price })
	}
	return products, nil
}

func TestProductsQueryUsesSharedCandidatePool(t *testing.T) {
	gin.SetMode(gin.TestMode)
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body broker.CandidateSearchRequest
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Error(err)
		}
		if r.URL.Path != "/infer/search/candidates" || body.Query != "red dress" || body.RetrievalMode != "hybrid" || body.EligibleProductIDs == nil || len(*body.EligibleProductIDs) != 3 {
			t.Errorf("candidate request lost context: %+v %s", body, r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprint(w, `{"status":"success","index_version":"old-serving","truncated":true,"search_config":{"retrieval_mode":"hybrid","effective_retrieval_mode":"hybrid","lexical_available":true},"data":[{"catalog_product_id":"a","vector_id":0},{"catalog_product_id":"b","vector_id":1},{"catalog_product_id":"c","vector_id":2}]}`)
	}))
	defer upstream.Close()
	fixture := &productSearchFixture{}
	client := broker.NewInferClient(upstream.URL, time.Second)
	service := searchservice.NewService(client, fixture)
	router := gin.New()
	NewProductHandler(fixture).WithSearchService(service).RegisterRoutes(router.Group("/api"))
	request := httptest.NewRequest("GET", "/api/products?q=red+dress&retrieval_mode=hybrid&page=2&limit=2&sort=price_asc&category=dress&featured=true&min_price=5&max_price=50", nil)
	out := httptest.NewRecorder()
	router.ServeHTTP(out, request)
	if out.Code != 200 {
		t.Fatalf("%d %s", out.Code, out.Body.String())
	}
	var response struct {
		Data       []catalog.Product          `json:"data"`
		Pagination struct{ Total, Pages int } `json:"pagination"`
		Search     models.SearchMetadata      `json:"search"`
	}
	if err := json.Unmarshal(out.Body.Bytes(), &response); err != nil {
		t.Fatal(err)
	}
	if fixture.browsed || fixture.version != "old-serving" || fixture.filter.Category != "dress" || !fixture.filter.Featured || fixture.filter.Min == nil || fixture.filter.Max == nil {
		t.Fatalf("query used browse or filters/version lost: %+v", fixture)
	}
	if response.Pagination.Total != 3 || response.Pagination.Pages != 2 || len(response.Data) != 1 || response.Data[0].ID != "a" || !response.Search.Truncated || response.Search.EffectiveRetrievalMode != "hybrid" {
		t.Fatalf("whole pool sorting/paging metadata lost: %s", out.Body.String())
	}
	out = httptest.NewRecorder()
	router.ServeHTTP(out, httptest.NewRequest("GET", "/api/products?q=red+dress&retrieval_mode=hybrid", nil))
	if out.Code != 200 || fixture.filter.Sort != "relevance" {
		t.Fatalf("query default is not relevance: %d %+v", out.Code, fixture.filter)
	}
}

func TestProductsBlankQueryStaysSQLAndQueryDefaultsRelevance(t *testing.T) {
	gin.SetMode(gin.TestMode)
	fixture := &productSearchFixture{}
	router := gin.New()
	NewProductHandler(fixture).RegisterRoutes(router.Group("/api"))
	out := httptest.NewRecorder()
	router.ServeHTTP(out, httptest.NewRequest("GET", "/api/products?q=++&category=dress", nil))
	if out.Code != 200 || !fixture.browsed || fixture.filter.Q != "" || fixture.filter.Sort != "newest" {
		t.Fatalf("blank query left SQL browse: %d %+v", out.Code, fixture)
	}
	for _, query := range []string{"q=boots&retrieval_mode=bad", "q=boots&sort=bad", "q=boots&min_price=10&max_price=5"} {
		out = httptest.NewRecorder()
		router.ServeHTTP(out, httptest.NewRequest("GET", "/api/products?"+query, nil))
		if out.Code != 400 {
			t.Fatalf("unexpected invalid configuration status: %d", out.Code)
		}
	}
}

func TestTextHybridUsesCandidateEndpointAndLimitsAfterHydration(t *testing.T) {
	gin.SetMode(gin.TestMode)
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/infer/search/candidates" {
			t.Error("hybrid used legacy dense route")
		}
		items := []broker.InferSearchResult{}
		for i := 0; i < 15; i++ {
			items = append(items, broker.InferSearchResult{VectorID: i, CatalogProductID: fmt.Sprint(i)})
		}
		json.NewEncoder(w).Encode(broker.InferResponse{Status: "success", IndexVersion: "pinned", Data: items, SearchConfig: broker.InferSearchConfig{RetrievalMode: "hybrid", EffectiveRetrievalMode: "dense", FallbackReason: "lexical_missing"}})
	}))
	defer upstream.Close()
	client := broker.NewInferClient(upstream.URL, time.Second)
	fixture := &productSearchFixture{}
	router := gin.New()
	NewSearchHandler(client).WithSearchService(searchservice.NewService(client, fixture)).RegisterRoutes(router.Group("/api"))
	form := url.Values{"query": {"boots"}, "mrl_dimension": {"512"}, "retrieval_mode": {"hybrid"}}
	request := httptest.NewRequest("POST", "/api/search/text", strings.NewReader(form.Encode()))
	request.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	out := httptest.NewRecorder()
	router.ServeHTTP(out, request)
	var response models.SearchAPIResponse
	if err := json.Unmarshal(out.Body.Bytes(), &response); err != nil {
		t.Fatal(err)
	}
	if out.Code != 200 || len(response.Data) != 10 || fixture.version != "pinned" || response.SearchConfig.FallbackReason != "lexical_missing" {
		t.Fatalf("text hybrid contract lost: %d %s", out.Code, out.Body.String())
	}
}

func TestTextHybridAcceptsLongDescriptions(t *testing.T) {
	gin.SetMode(gin.TestMode)
	query := strings.Repeat("Soft cotton shirt with a relaxed fit. ", 12) + "Blue sleeves."
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var request broker.CandidateSearchRequest
		if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
			t.Error(err)
		}
		if r.URL.Path != "/infer/search/candidates" || request.Query != query {
			t.Errorf("long description was rejected or changed: path=%s query=%q", r.URL.Path, request.Query)
		}
		json.NewEncoder(w).Encode(broker.InferResponse{Status: "success", IndexVersion: "pinned", Data: []broker.InferSearchResult{}})
	}))
	defer upstream.Close()
	router := gin.New()
	NewSearchHandler(broker.NewInferClient(upstream.URL, time.Second)).RegisterRoutes(router.Group("/api"))
	form := url.Values{"query": {query}, "mrl_dimension": {"512"}, "retrieval_mode": {"hybrid"}}
	request := httptest.NewRequest("POST", "/api/search/text", strings.NewReader(form.Encode()))
	request.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	out := httptest.NewRecorder()
	router.ServeHTTP(out, request)
	if out.Code != http.StatusOK {
		t.Fatalf("long hybrid description failed: %d %s", out.Code, out.Body.String())
	}
}
