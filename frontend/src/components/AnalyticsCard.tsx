import { motion } from "framer-motion";
import { LucideIcon } from "lucide-react";

interface AnalyticsCardProps {
  title: string;
  value: string;
  icon: LucideIcon;
  change?: string;
  positive?: boolean;
}

const AnalyticsCard = ({ title, value, icon: Icon, change, positive }: AnalyticsCardProps) => {
  return (
    <motion.div
      className="bg-card rounded-xl p-6 card-shadow"
      whileHover={{ y: -1 }}
      transition={{ type: "spring", duration: 0.3, bounce: 0 }}
    >
      <div className="flex items-start justify-between">
        <div>
          <p className="text-[13px] text-muted-foreground font-medium">{title}</p>
          <p className="text-[30px] font-semibold tracking-tight mt-1 tabular-nums text-card-foreground">
            {value}
          </p>
          {change && (
            <p className={`text-xs mt-1 font-medium ${positive ? "text-success" : "text-destructive"}`}>
              {change}
            </p>
          )}
        </div>
        <div className="w-10 h-10 rounded-lg bg-secondary flex items-center justify-center">
          <Icon className="w-5 h-5 text-muted-foreground" />
        </div>
      </div>
    </motion.div>
  );
};

export default AnalyticsCard;
