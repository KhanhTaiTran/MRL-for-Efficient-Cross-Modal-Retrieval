import { AuraFindApp } from "components/aurafind/aura-find-app";

export const metadata = {
  title: "AuraFind — AI-First Fashion",
  description:
    "Discover fashion with AI-powered visual search. Text-to-image and image-to-image retrieval with Matryoshka Representation Learning.",
  openGraph: {
    type: "website",
  },
};

export default function HomePage() {
  return <AuraFindApp />;
}
