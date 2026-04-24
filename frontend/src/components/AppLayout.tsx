import { Outlet, useLocation } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { Sidebar } from "@/components/Sidebar";
import { Navbar } from "@/components/Navbar";
import { RouteErrorBoundary } from "@/components/layout/RouteErrorBoundary";

export function AppLayout() {
  const location = useLocation();

  return (
    <div className="flex h-screen w-full bg-[#F8FAFC] dark:bg-background">
      <Sidebar />

      <div className="flex h-screen min-w-0 flex-1 flex-col overflow-hidden">
        <Navbar />

        <main className="flex-1 overflow-y-auto p-6 lg:p-8">
          <AnimatePresence mode="wait">
            <motion.div
              key={location.pathname}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
              className="mx-auto max-w-[1600px]"
            >
              <RouteErrorBoundary>
                <Outlet />
              </RouteErrorBoundary>
            </motion.div>
          </AnimatePresence>
        </main>
      </div>
    </div>
  );
}
