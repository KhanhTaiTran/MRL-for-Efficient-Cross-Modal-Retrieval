import { ReviewModeration } from "components/admin/review-moderation";
export const metadata = {
  title: "Review moderation",
  robots: { index: false, follow: false },
};
export default function Page() {
  return <ReviewModeration />;
}
