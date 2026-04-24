import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AppLayout } from "@/components/AppLayout";
import Dashboard from "@/pages/Dashboard.tsx";
import Students from "@/pages/Students";
import HRContacts from "@/pages/HRContacts";
import Outreach from "@/pages/Outreach";
import Campaigns from "@/pages/Campaigns";
import CampaignLifecycle from "@/pages/CampaignLifecycle";
import FollowUps from "@/pages/FollowUps.tsx";
import PriorityQueue from "@/pages/PriorityQueue";
import DecisionDiagnostics from "@/pages/DecisionDiagnostics";
import Replies from "@/pages/Replies";
import EmailLogs from "@/pages/EmailLogs";
import AnalyticsStudents from "@/pages/AnalyticsStudents";
import AnalyticsHRs from "@/pages/AnalyticsHRs";
import AnalyticsTemplates from "@/pages/AnalyticsTemplates";
import AdminTools from "@/pages/AdminTools";
import SystemReliability from "@/pages/SystemReliability";
import Settings from "@/pages/Settings";
import ObservabilityConsole from "@/pages/ObservabilityConsole";
import NotFound from "@/pages/NotFound";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <Toaster />
        <Sonner />
        <BrowserRouter>
          <Routes>
            <Route element={<AppLayout />}>
              <Route path="/" element={<Dashboard />} />
              <Route path="/students" element={<Students />} />
              <Route path="/hr-contacts" element={<HRContacts />} />
              <Route path="/outreach" element={<Outreach />} />
              <Route path="/campaigns" element={<Campaigns />} />
              <Route path="/campaign-lifecycle" element={<CampaignLifecycle />} />
              <Route path="/followups" element={<FollowUps />} />
              <Route path="/priority-queue" element={<PriorityQueue />} />
              <Route path="/decision-diagnostics" element={<DecisionDiagnostics />} />
              <Route path="/replies" element={<Replies />} />
              <Route path="/email-logs" element={<EmailLogs />} />
              <Route path="/analytics/students" element={<AnalyticsStudents />} />
              <Route path="/analytics/hrs" element={<AnalyticsHRs />} />
              <Route path="/analytics/templates" element={<AnalyticsTemplates />} />
              <Route path="/admin" element={<AdminTools />} />
              <Route path="/admin/observability" element={<ObservabilityConsole />} />
              <Route path="/system-reliability" element={<SystemReliability />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="*" element={<NotFound />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </TooltipProvider>
    </QueryClientProvider>
  );
}
