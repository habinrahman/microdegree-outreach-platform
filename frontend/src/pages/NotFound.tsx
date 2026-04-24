import { useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import { motion } from "framer-motion";

import { PremiumCard } from "@/components/layout/PremiumCard";
import { Button } from "@/components/ui/button";

const NotFound = () => {
  const location = useLocation();

  useEffect(() => {
    console.error("404 Error: User attempted to access non-existent route:", location.pathname);
  }, [location.pathname]);

  return (
    <div className="flex min-h-[50vh] items-center justify-center py-12">
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}>
        <PremiumCard className="max-w-md p-10 text-center shadow-md">
          <h1 className="text-3xl font-bold tracking-tight text-foreground">404</h1>
          <p className="mt-2 text-lg font-semibold">Page not found</p>
          <p className="mt-2 text-sm text-gray-500 dark:text-muted-foreground">
            The route <code className="rounded bg-muted px-1 py-0.5 text-xs">{location.pathname}</code> does not exist.
          </p>
          <Button className="mt-6" asChild>
            <Link to="/">Return to dashboard</Link>
          </Button>
        </PremiumCard>
      </motion.div>
    </div>
  );
};

export default NotFound;
