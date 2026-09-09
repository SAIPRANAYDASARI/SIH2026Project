import { Route, Routes } from "react-router-dom";

import { ChatPage } from "@/pages/ChatPage";
import { OfficerDashboard } from "@/pages/OfficerDashboard";
import { ToolsPage } from "@/pages/ToolsPage";

/**
 * Top-level route table. `/` is the chat UI (Step 7); `/dashboard` is the
 * officer analytics dashboard (Step 11); `/tools` is the certification
 * wizard / licence verification / gap-check trio (F4/F8), previously only
 * reachable as raw API endpoints. `BrowserRouter` is provided by
 * `main.tsx` so this component itself stays testable with `MemoryRouter`
 * (see `App.test.tsx`) without needing real browser history.
 */
export function App(): JSX.Element {
  return (
    <Routes>
      <Route path="/" element={<ChatPage />} />
      <Route path="/dashboard" element={<OfficerDashboard />} />
      <Route path="/tools" element={<ToolsPage />} />
    </Routes>
  );
}
