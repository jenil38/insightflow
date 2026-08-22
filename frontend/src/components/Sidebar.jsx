import { useNavigate, useLocation } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { LayoutDashboard, Database, LogOut, Sparkles } from "lucide-react";

export default function Sidebar({ user, datasets, onLogout }) {
  const navigate = useNavigate();
  const location = useLocation();

  return (
    <aside className="w-64 shrink-0 h-screen sticky top-0 glass border-y-0 border-l-0 flex flex-col p-4 z-20">
      <motion.div
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex items-center gap-2 px-2 py-3 mb-4"
      >
        <motion.div
          whileHover={{ rotate: 12, scale: 1.08 }}
          className="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-500 to-fuchsia-500 flex items-center justify-center shadow-lg shadow-indigo-500/30"
        >
          <Sparkles size={16} className="text-white" />
        </motion.div>
        <span className="font-semibold gradient-text text-lg">InsightFlow AI</span>
      </motion.div>

      <NavItem
        active={location.pathname === "/"}
        icon={LayoutDashboard}
        label="Home"
        onClick={() => navigate("/")}
      />

      <p className="text-xs text-slate-400 uppercase tracking-wide px-3 mt-6 mb-2">Workspaces</p>
      <div className="flex-1 overflow-y-auto space-y-1">
        <AnimatePresence>
          {datasets.map((d) => (
            <motion.div
              key={d.id}
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -8 }}
            >
              <NavItem
                active={location.pathname === `/workspace/${d.id}`}
                icon={Database}
                label={d.filename}
                onClick={() => navigate(`/workspace/${d.id}`)}
                truncate
              />
            </motion.div>
          ))}
        </AnimatePresence>
        {datasets.length === 0 && (
          <p className="text-xs text-slate-400 px-3">No workspaces yet</p>
        )}
      </div>

      <div className="border-t border-white/60 pt-3 mt-3">
        <div className="px-3 mb-2">
          <p className="text-xs text-slate-400">Signed in as</p>
          <p className="text-sm text-slate-700 truncate font-medium">{user?.full_name || user?.email}</p>
        </div>
        <NavItem icon={LogOut} label="Log out" onClick={onLogout} />
      </div>
    </aside>
  );
}

function NavItem({ active, icon: Icon, label, onClick, truncate }) {
  return (
    <button
      onClick={onClick}
      className="relative w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm text-left transition-colors mb-0.5"
    >
      {active && (
        <motion.div
          layoutId="sidebar-active-pill"
          className="absolute inset-0 glass rounded-xl"
          transition={{ type: "spring", stiffness: 400, damping: 32 }}
        />
      )}
      <span className={`relative z-10 flex items-center gap-3 ${active ? "text-slate-900" : "text-slate-500 hover:text-slate-800"}`}>
        <Icon size={16} className="shrink-0" />
        <span className={truncate ? "truncate" : ""}>{label}</span>
      </span>
    </button>
  );
}
