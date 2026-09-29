import { Suspense } from "react";

import { LoginForm } from "@/features/studio/auth/AuthForms";

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
