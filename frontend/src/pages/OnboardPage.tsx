import { OnboardingWizard } from '@/components/onboarding/OnboardingWizard';

export function OnboardPage() {
  return (
    <div className="h-[calc(100vh-3.5rem)] overflow-y-auto nb-scroll bg-bg-elev-1/30">
      <OnboardingWizard />
    </div>
  );
}
