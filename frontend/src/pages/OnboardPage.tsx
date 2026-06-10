import { Navigate } from "react-router-dom";
import { OnboardingWizard } from "@/components/onboarding/OnboardingWizard";
import { useAuthStore } from "@/store/auth";

export function OnboardPage() {
  // Onboarding stores device credentials and is admin-only on the API
  // (test-connection / discover / create all require_admin) — don't render a
  // wizard the user can't complete.
  const role = useAuthStore((s) => s.user?.role);
  if (role !== "admin") return <Navigate to="/" replace />;

  return (
    <div className="h-[calc(100vh-3.5rem)] overflow-y-auto nb-scroll bg-bg-elev-1/30">
      <OnboardingWizard />
    </div>
  );
}
