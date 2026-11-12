"use client";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  Suspense,
} from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { getProduct } from "lib/api/catalog";
import { displayText } from "lib/display-text";
import {
  fetchProductImageAsFile,
  fetchSearchConfig,
  getSearchErrorMessage,
  searchByImage,
  searchByText,
} from "./search-api";
import { enrichProduct, type EnrichedProduct } from "./types";
type SearchTarget = { q?: string; similar?: string; upload?: string };
type Upload = { file: File; preview: string };
type SearchState = {
  query: string;
  setQuery: (q: string) => void;
  selected: Upload | null;
  selectImage: (file: File) => void;
  clearImage: () => void;
  submit: () => void;
  execute: (target: SearchTarget, force?: boolean) => Promise<void>;
  results: EnrichedProduct[];
  loading: boolean;
  error: string;
  title: string;
  config: Awaited<ReturnType<typeof fetchSearchConfig>> | null;
};
const Context = createContext<SearchState | null>(null);

function CatalogQuerySync() {
  const pathname = usePathname();
  const params = useSearchParams();
  const query = params.get("q") ?? "";
  const { setQuery, clearImage } = useSearch();
  useEffect(() => {
    if (pathname === "/search") {
      setQuery(query);
      clearImage();
    }
  }, [pathname, query, setQuery, clearImage]);
  return null;
}
export function SearchProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Upload | null>(null);
  const [results, setResults] = useState<EnrichedProduct[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [title, setTitle] = useState("Find your next favourite");
  const [config, setConfig] = useState<SearchState["config"]>(null);
  const dimension = useRef(512);
  const retrievalMode = useRef<"dense" | "hybrid">("dense");
  const lastKey = useRef("");
  const lastView = useRef<{
    query: string;
    selected: Upload | null;
    title: string;
  } | null>(null);
  const requestId = useRef(0);
  const uploads = useRef(new Map<string, Upload>());
  const previewUrls = useRef(new Set<string>());
  useEffect(() => {
    let alive = true;
    fetchSearchConfig()
      .then((value) => {
        if (alive) {
          dimension.current = value.default_dim;
          retrievalMode.current = value.text_retrieval_mode_default ?? "dense";
          setConfig(value);
        }
      })
      .catch(() => {});
    const urls = previewUrls.current;
    return () => {
      alive = false;
      urls.forEach((url) => URL.revokeObjectURL(url));
    };
  }, []);
  const clearImage = useCallback(() => setSelected(null), []);
  const selectImage = useCallback((file: File) => {
    if (!file.type.startsWith("image/")) {
      setError("Choose a supported image file.");
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setError("Choose an image smaller than 10 MB.");
      return;
    }
    const preview = URL.createObjectURL(file);
    previewUrls.current.add(preview);
    const upload = { file, preview };
    setSelected(upload);
    setError("");
    return upload;
  }, []);
  const execute = useCallback(
    async (target: SearchTarget, force = false) => {
      const key = JSON.stringify(target);
      if (!force && key === lastKey.current) {
        if (lastView.current) {
          setQuery(lastView.current.query);
          setSelected(lastView.current.selected);
          setTitle(lastView.current.title);
        }
        return;
      }
      lastKey.current = key;
      lastView.current = null;
      const id = ++requestId.current;
      setError("");
      setLoading(true);
      setResults([]);
      try {
        let file: File | undefined;
        if (target.similar) {
          setTitle("Similar styles");
          const { data } = await getProduct(target.similar);
          file = await fetchProductImageAsFile(
            data.id,
            data.image_url,
            data.name,
          );
          if (id !== requestId.current) return;
          const selected = selectImage(file);
          if (!selected)
            throw new Error("This product image could not be used for search.");
          setQuery("");
          const title = `Similar to ${displayText(data.name)}`;
          setTitle(title);
          lastView.current = { query: "", selected, title };
        } else if (target.upload) {
          const upload = uploads.current.get(target.upload);
          if (!upload)
            throw new Error(
              "Upload your reference image again using the camera in the search bar. Image uploads are kept only in this browser session.",
            );
          file = upload.file;
          setSelected(upload);
          setQuery("");
          setTitle("Styles inspired by your image");
          lastView.current = {
            query: "",
            selected: upload,
            title: "Styles inspired by your image",
          };
        } else if (target.q?.trim()) {
          setQuery(target.q);
          setSelected(null);
          setTitle(`Results for “${target.q}”`);
          lastView.current = {
            query: target.q,
            selected: null,
            title: `Results for “${target.q}”`,
          };
        } else {
          setTitle("Find your next favourite");
          return;
        }
        if (!file) {
          try {
            const current = await fetchSearchConfig();
            if (id !== requestId.current) return;
            dimension.current = current.default_dim;
            retrievalMode.current =
              current.text_retrieval_mode_default ?? "dense";
            setConfig(current);
          } catch {
            retrievalMode.current = "dense";
          }
        }
        const response = file
          ? await searchByImage(file, dimension.current, "adaptive")
          : await searchByText(
              target.q!,
              dimension.current,
              "adaptive",
              retrievalMode.current,
            );
        if (id === requestId.current)
          setResults(response.data.map(enrichProduct));
      } catch (err) {
        if (id === requestId.current) setError(getSearchErrorMessage(err));
      } finally {
        if (id === requestId.current) setLoading(false);
      }
    },
    [selectImage],
  );
  const submit = () => {
    let target: SearchTarget;
    let url: string;
    if (selected) {
      const upload = crypto.randomUUID();
      uploads.current.set(upload, selected);
      target = { upload };
      url = `/discover?upload=${upload}`;
    } else {
      if (!query.trim()) return;
      if (window.location.pathname === "/search") {
        const params = new URLSearchParams(window.location.search);
        params.set("q", query.trim());
        params.delete("page");
        router.push(`/search?${params}`);
        return;
      }
      target = { q: query.trim() };
      url = `/discover?q=${encodeURIComponent(query.trim())}`;
    }
    router.push(url);
    void execute(target, true);
  };
  return (
    <Context.Provider
      value={{
        query,
        setQuery,
        selected,
        selectImage,
        clearImage,
        submit,
        execute,
        results,
        loading,
        error,
        title,
        config,
      }}
    >
      <Suspense fallback={null}>
        <CatalogQuerySync />
      </Suspense>
      {children}
    </Context.Provider>
  );
}
export function useSearch() {
  const value = useContext(Context);
  if (!value) throw new Error("SearchProvider is required.");
  return value;
}
