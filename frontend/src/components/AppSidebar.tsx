import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  GraduationCap,
  Users,
  Send,
  Mail,
  Settings,
  Inbox,
  BarChart3,
  Wrench,
  Megaphone,
} from "lucide-react";

const navItems: { label: string; icon: typeof LayoutDashboard; to: string }[] = [
  { label: "Dashboard", icon: LayoutDashboard, to: "/" },
  { label: "Students", icon: GraduationCap, to: "/students" },
  { label: "HR Contacts", icon: Users, to: "/hr-contacts" },
  { label: "Outreach", icon: Send, to: "/outreach" },
  { label: "Campaigns", icon: Megaphone, to: "/campaigns" },
  { label: "Replies", icon: Inbox, to: "/replies" },
  { label: "Email Logs", icon: Mail, to: "/email-logs" },
  { label: "Analytics · Students", icon: BarChart3, to: "/analytics/students" },
  { label: "Analytics · HRs", icon: BarChart3, to: "/analytics/hrs" },
  { label: "Analytics · Templates", icon: BarChart3, to: "/analytics/templates" },
  { label: "Admin Tools", icon: Wrench, to: "/admin" },
  { label: "System Status", icon: Settings, to: "/settings" },
];

const AppSidebar = () => {
  return (
    <aside
      className="fixed left-0 top-0 bottom-0 w-60 flex flex-col overflow-y-auto"
      style={{ backgroundColor: "hsl(var(--sidebar-background))" }}
    >
      <div className="px-6 py-6 shrink-0">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg flex items-center justify-center bg-primary">
            <Send className="w-4 h-4 text-primary-foreground" />
          </div>
          <span
            className="text-sm font-semibold tracking-tight"
            style={{ color: "hsl(var(--sidebar-foreground-active))" }}
          >
            MicroDegree Outreach
          </span>
        </div>
      </div>

      <nav className="flex-1 px-3 space-y-0.5 pb-6">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
            className={({ isActive }) =>
              `sidebar-nav-item ${isActive ? "active" : ""}`
            }
          >
            <item.icon className="w-[18px] h-[18px] shrink-0" />
            <span className="leading-tight">{item.label}</span>
          </NavLink>
        ))}
      </nav>

      <div
        className="px-6 py-5 border-t shrink-0"
        style={{ borderColor: "rgba(255,255,255,0.06)" }}
      >
        <p
          className="text-xs"
          style={{ color: "hsl(var(--sidebar-foreground))", opacity: 0.5 }}
        >
          © 2026 MicroDegree Outreach
        </p>
      </div>
    </aside>
  );
};

export default AppSidebar;
