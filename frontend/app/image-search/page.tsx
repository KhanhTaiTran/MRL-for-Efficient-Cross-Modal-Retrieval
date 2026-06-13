"use client";

import Image from "next/image";
import { useState } from "react";

// Define the structure of search results
interface SearchResult {
  product_id: string;
  distance: number;
}

export default function ImageSearchPage() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [results, setResults] = useState<SearchResult[]>([]);

  // handle file selection
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      setSelectedFile(file);
      setPreviewUrl(URL.createObjectURL(file));
    }
  };

  // process call API to Core API
  const handleSearch = async () => {
    if (!selectedFile) return;

    setIsLoading(true);
    setResults([]);

    const formData = new FormData();
    formData.append("image", selectedFile);

    try {
      // TODO: Call API to Core API
      const response = await fetch("http://localhost:8080/api/search", {
        method: "POST",
        body: formData,
      });

      const data = await response.json();
      if (data.status === "success") {
        setResults(data.data);
      } else {
        alert("Error: " + data.message);
      }
    } catch (error) {
      console.error("Error calling API:", error);
      alert("Cannot connect to the search system.");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto p-8">
      <h1 className="text-3xl font-bold mb-8 text-center">Visual Search MRL</h1>

      {/* Upload Area */}
      <div className="flex flex-col items-center justify-center p-6 border-2 border-dashed border-gray-300 rounded-lg bg-gray-50 mb-8">
        <input
          title="Upload an image to search for similar products"
          type="file"
          accept="image/*"
          onChange={handleFileChange}
          className="mb-4"
        />
        {previewUrl && (
          <div className="mt-4">
            <Image
              src={previewUrl}
              alt="Preview"
              width={200}
              height={200}
              className="rounded-lg object-cover shadow-md"
            />
          </div>
        )}
        <button
          onClick={handleSearch}
          disabled={!selectedFile || isLoading}
          className="mt-6 px-6 py-2 bg-black text-white rounded-md font-semibold hover:bg-gray-800 disabled:bg-gray-400 transition-colors"
        >
          {isLoading ? "Scanning FAISS..." : "Search Products"}
        </button>
      </div>

      {/* Results Area */}
      {results.length > 0 && (
        <div>
          <h2 className="text-2xl font-semibold mb-4">Search Results</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {results.map((item, index) => (
              <div
                key={index}
                className="border rounded-lg p-4 flex flex-col items-center bg-white shadow-sm hover:shadow-md transition-shadow"
              >
                {/* Considering we don't have actual image URLs, we can use a placeholder or the product ID as a label. 
                In a real application, the src would come from the Backend/CDN, here we use the file name as a simulation
                 */}
                <div className="w-full aspect-square bg-gray-100 rounded-md mb-4 flex items-center justify-center overflow-hidden relative border border-gray-200">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={`/mock_data/${item.product_id}`}
                    alt={item.product_id}
                    className="object-cover w-full h-full hover:scale-110 transition-transform duration-300"
                  />
                </div>
                <h3 className="text-lg font-medium">{item.product_id}</h3>
                <p className="text-sm text-gray-500">
                  Distance: {item.distance.toFixed(4)}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
