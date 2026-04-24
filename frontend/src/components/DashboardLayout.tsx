import { ReactNode } from "react";
import { motion, AnimatePresence } from "framer-motion";
import AppSidebar from "./AppSidebar";

interface DashboardLayoutProps {
  children: ReactNode;
  title: string;
  subtitle?: string;
}

const DashboardLayout = ({ children, title, subtitle }: DashboardLayoutProps) => {
  return (
    <div className="min-h-screen flex">
      <AppSidebar />
      <main className="flex-1 ml-60 p-8 lg:p-12">
        <AnimatePresence mode="wait">
          <motion.div
            key={title}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
          >
            <div className="mb-8">
              <h1 className="text-[30px] font-semibold tracking-tight text-foreground">
                {title}
              </h1>
              {subtitle && (
                <p className="text-sm text-muted-foreground mt-1">{subtitle}</p>
              )}
            </div>
            {children}
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  );
};

export default DashboardLayout;
