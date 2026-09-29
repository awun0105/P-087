import { Suspense } from "react";

import { RegisterForm } from "@/features/studio/auth/AuthForms";

export default function RegisterPage() {
  return (
    <Suspense>
      <RegisterForm />
    </Suspense>
  );
}
