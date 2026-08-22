/**
 * Responsive application shell.
 *
 * Layout: collapsible sidebar on desktop, off-canvas drawer on mobile, topbar
 * with breadcrumbs, dataset search, theme toggle, API health, and user menu.
 *
 * Only navigation that actually works appears here. Per-dataset features live
 * inside the workspace, not as global pages, because they have no meaning
 * without a dataset selected.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, NavLink, useLocation, useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import {
  Activity, ChevronLeft, ChevronRight, Database, LayoutDashboard, LogOut,
  Menu, Moon, PanelLeftClose, Search, Settings, Sun, Upload, User, X,
} from "lucide-react";

import { datasets as datasetsApi, ops } from "../../api/endpoints.js";
import { useAuth, useTheme } from "../../app/providers.jsx";
import { Badge, Button, IconButton, Tooltip } from "../ui/index.jsx";

const SIDEBAR_KEY = "if_sidebar_collapsed";

export default function AppShell({ children, onUploadClick }) {
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(SIDEBAR_KEY) === "1");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const location = useLocation();

  useEffect(() => {
    localStorage.setItem(SIDEBAR_KEY, collapsed ? "1" : "0");
  }, [collapsed]);

  // Close the mobile drawer on navigation, otherwise it covers the page you
  // just navigated to.
  useEffect(() => {
    setDrawerOpen(false);
  }, [location.pathname]);

  return (
    <div className="flex h-full min-h-screen bg-canvas">
      <a href="#main-content" className="skip-link">Skip to main content</a>

      {/* Desktop sidebar. Sits above the canvas as its own slab: a vertical
          fill gradient plus a right-edge shadow, so the main column reads as
          set back rather than merely divided by a line. */}
      <aside
        className={clsx(
          "relative z-20 hidden shrink-0 border-r border-line bg-gradient-to-b from-lift to-surface",
          "shadow-[4px_0_24px_-8px_rgb(var(--shadow-rgb)/0.12)] transition-[width] duration-200 lg:block",
          collapsed ? "w-16" : "w-64",
        )}
      >
        <SidebarContent
          collapsed={collapsed}
          onToggleCollapse={() => setCollapsed((value) => !value)}
          onUploadClick={onUploadClick}
        />
      </aside>

      {/* Mobile drawer */}
      {drawerOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div
            className="absolute inset-0 bg-ink/50 backdrop-blur-md"
            onClick={() => setDrawerOpen(false)}
            aria-hidden="true"
          />
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Navigation"
            className="relative z-10 h-full w-72 animate-slide-up border-r border-line
                       bg-gradient-to-b from-lift to-surface shadow-depth-4"
          >
            <SidebarContent
              collapsed={false}
              onClose={() => setDrawerOpen(false)}
              onUploadClick={onUploadClick}
            />
          </div>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar onOpenDrawer={() => setDrawerOpen(true)} onUploadClick={onUploadClick} />
        <main id="main-content" className="min-w-0 flex-1 px-4 py-6 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-[1600px]">{children}</div>
        </main>
      </div>
    </div>
  );
}

/* ----------------------------------------------------------------- sidebar */

function SidebarContent({ collapsed, onToggleCollapse, onClose, onUploadClick }) {
  const [search, setSearch] = useState("");
  const { data: datasets = [] } = useQuery({
    queryKey: ["datasets"],
    queryFn: datasetsApi.list,
    staleTime: 60_000,
  });

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return datasets;
    return datasets.filter((d) => d.filename.toLowerCase().includes(needle));
  }, [datasets, search]);

  return (
    <div className="flex h-full flex-col">
      {/* Brand */}
      <div className={clsx("flex h-14 items-center gap-2 border-b border-line px-3", collapsed && "justify-center")}>
        <Link
          to="/"
          className="flex min-w-0 items-center gap-2 rounded focus-visible:ring-2 focus-visible:ring-accent/50"
        >
          <span
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent-lift
                       text-accent-contrast shadow-rim glow-accent"
            aria-hidden="true"
          >
            <Activity size={16} />
          </span>
          {!collapsed && (
            <span className="truncate text-base font-semibold tracking-[-0.02em] text-ink">
              Insight<span className="text-luxe">Flow</span>
            </span>
          )}
        </Link>
        <div className="ml-auto flex items-center">
          {onClose && <IconButton icon={X} label="Close navigation" onClick={onClose} size="sm" />}
        </div>
      </div>

      {/* Primary nav */}
      <nav className="px-2 py-3" aria-label="Main">
        <NavItem to="/" icon={LayoutDashboard} label="Overview" collapsed={collapsed} end />
        <NavItem to="/datasets" icon={Database} label="Datasets" collapsed={collapsed} />
        <NavItem to="/settings" icon={Settings} label="Settings" collapsed={collapsed} />
      </nav>

      {/* Dataset list */}
      <div className="flex min-h-0 flex-1 flex-col border-t border-line pt-3">
        {!collapsed && (
          <>
            <div className="flex items-center justify-between px-4 pb-2">
              <p className="text-2xs font-semibold uppercase tracking-wider text-subtle">
                Recent workspaces
              </p>
              {datasets.length > 0 && (
                <span className="text-2xs tabular-nums text-subtle">{datasets.length}</span>
              )}
            </div>
            {datasets.length > 4 && (
              <div className="relative px-3 pb-2">
                <Search
                  size={13}
                  aria-hidden="true"
                  className="pointer-events-none absolute left-6 top-1/2 -translate-y-1/2 text-subtle"
                />
                <input
                  type="search"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Filter datasets"
                  aria-label="Filter datasets"
                  className="input-base h-8 py-1 pl-7 text-sm"
                />
              </div>
            )}
          </>
        )}

        <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
          {filtered.map((dataset) => (
            <NavItem
              key={dataset.id}
              to={`/workspace/${dataset.id}`}
              icon={Database}
              label={dataset.filename}
              collapsed={collapsed}
              truncate
            />
          ))}
          {!collapsed && datasets.length === 0 && (
            <p className="px-2 py-1 text-sm text-subtle">No datasets yet.</p>
          )}
          {!collapsed && datasets.length > 0 && filtered.length === 0 && (
            <p className="px-2 py-1 text-sm text-subtle">No matches.</p>
          )}
        </div>
      </div>

      {/* Footer */}
      <div className="border-t border-line p-2">
        {collapsed ? (
          <div className="flex justify-center">
            <IconButton icon={Upload} label="Upload dataset" onClick={onUploadClick} />
          </div>
        ) : (
          <Button icon={Upload} className="w-full" onClick={onUploadClick}>
            Upload dataset
          </Button>
        )}
        {onToggleCollapse && (
          <div className={clsx("mt-1 flex", collapsed ? "justify-center" : "justify-end")}>
            <IconButton
              icon={collapsed ? ChevronRight : PanelLeftClose}
              label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              onClick={onToggleCollapse}
              size="sm"
            />
          </div>
        )}
      </div>
    </div>
  );
}

function NavItem({ to, icon: Icon, label, collapsed, truncate, end }) {
  const content = (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        clsx(
          "mb-0.5 flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-base",
          "transition-[background-color,color,box-shadow,transform] duration-200",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50",
          collapsed && "justify-center px-0",
          isActive
            // The active row lifts out of the rail; inactive rows stay flat so
            // exactly one item reads as raised at a time.
            ? "bg-accent-soft font-medium text-accent shadow-rim shadow-depth-1"
            : "text-muted hover:translate-x-0.5 hover:bg-surface hover:text-ink",
        )
      }
    >
      <Icon size={16} className="shrink-0" aria-hidden="true" />
      {!collapsed && <span className={clsx("min-w-0", truncate && "truncate")}>{label}</span>}
    </NavLink>
  );

  // Collapsed rail has no visible labels, so the name moves into a tooltip.
  return collapsed ? <Tooltip content={label}>{content}</Tooltip> : content;
}

/* ------------------------------------------------------------------ top bar */

function TopBar({ onOpenDrawer, onUploadClick }) {
  const { user, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef(null);

  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: ops.health,
    staleTime: 30_000,
    refetchInterval: 60_000,
    retry: false,
  });

  useEffect(() => {
    if (!menuOpen) return undefined;
    function onPointerDown(event) {
      if (!menuRef.current?.contains(event.target)) setMenuOpen(false);
    }
    function onKeyDown(event) {
      if (event.key === "Escape") setMenuOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [menuOpen]);

  async function handleLogout() {
    setMenuOpen(false);
    await logout();
    navigate("/login", { replace: true });
  }

  return (
    <header
      className="sticky top-0 z-30 flex h-16 shrink-0 items-center gap-2 border-b border-line
                 bg-surface/80 px-4 backdrop-blur-xl backdrop-saturate-150 sm:px-6
                 shadow-[0_4px_20px_-8px_rgb(var(--shadow-rgb)/0.14)]"
    >
      <div className="lg:hidden">
        <IconButton icon={Menu} label="Open navigation" onClick={onOpenDrawer} />
      </div>

      <Breadcrumbs />

      <div className="ml-auto flex items-center gap-1.5">
        <HealthIndicator health={health} />
        <div className="hidden sm:block">
          <Button variant="secondary" size="sm" icon={Upload} onClick={onUploadClick}>
            Upload
          </Button>
        </div>
        <IconButton
          icon={theme === "dark" ? Sun : Moon}
          label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
          onClick={toggleTheme}
        />

        <div className="relative" ref={menuRef}>
          <button
            type="button"
            onClick={() => setMenuOpen((open) => !open)}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            className="flex items-center gap-2 rounded-md px-1.5 py-1 text-base text-muted transition-colors
                       hover:bg-canvas hover:text-ink focus-visible:outline-none focus-visible:ring-2
                       focus-visible:ring-accent/50"
          >
            <span
              className="flex h-8 w-8 items-center justify-center rounded-full bg-accent-lift
                         text-xs font-semibold text-accent-contrast shadow-rim shadow-depth-1"
              aria-hidden="true"
            >
              {initials(user)}
            </span>
            <span className="hidden max-w-[10rem] truncate sm:block">
              {user?.full_name || user?.email || "Account"}
            </span>
          </button>

          {menuOpen && (
            <div
              role="menu"
              className="absolute right-0 top-full z-40 mt-2 w-60 animate-rise-3d overflow-hidden
                         rounded-xl border border-line bg-elevated shadow-rim shadow-depth-4"
            >
              <div className="border-b border-line/70 px-3 py-2.5">
                <p className="truncate text-base font-medium text-ink">{user?.full_name || "Signed in"}</p>
                <p className="truncate text-sm text-muted">{user?.email}</p>
                {user && !user.is_verified && (
                  <Badge tone="warning" className="mt-1.5">Email not verified</Badge>
                )}
              </div>
              <Link
                role="menuitem"
                to="/settings"
                onClick={() => setMenuOpen(false)}
                className="flex w-full items-center gap-2 px-3 py-2.5 text-left text-base text-muted
                           transition-colors hover:bg-canvas hover:text-ink focus-visible:outline-none
                           focus-visible:bg-canvas"
              >
                <Settings size={15} aria-hidden="true" />
                Settings
              </Link>
              <button
                role="menuitem"
                onClick={handleLogout}
                className="flex w-full items-center gap-2 border-t border-line px-3 py-2.5 text-left
                           text-base text-muted transition-colors hover:bg-canvas hover:text-ink
                           focus-visible:outline-none focus-visible:bg-canvas"
              >
                <LogOut size={15} aria-hidden="true" />
                Sign out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}

function initials(user) {
  if (user?.full_name) {
    return user.full_name
      .split(/\s+/)
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase())
      .join("");
  }
  return user?.email?.[0]?.toUpperCase() || "?";
}

function HealthIndicator({ health }) {
  const reachable = Boolean(health);
  const degraded = health && health.status !== "ok";

  const tone = !reachable ? "danger" : degraded ? "warning" : "success";
  const label = !reachable ? "API unreachable" : degraded ? "API degraded" : "API healthy";
  const detail = !reachable
    ? "The frontend cannot reach the backend. Check that it is running."
    : `${label}. Database ${health.database}. Version ${health.version}.` +
      (health.features?.copilot ? " AI Copilot configured." : " AI Copilot not configured.");

  return (
    <Tooltip content={detail}>
      <span className="flex items-center gap-1.5 rounded-md px-2 py-1" role="status" aria-label={detail}>
        <span
          aria-hidden="true"
          className={clsx(
            "h-1.5 w-1.5 shrink-0 rounded-full",
            tone === "success" && "bg-success",
            tone === "warning" && "bg-warning",
            tone === "danger" && "bg-danger",
          )}
        />
        <span className="hidden text-sm text-muted xl:block">{label}</span>
      </span>
    </Tooltip>
  );
}

/* -------------------------------------------------------------- breadcrumbs */

function Breadcrumbs() {
  const location = useLocation();
  const { id } = useParams();
  const { data: dataset } = useQuery({
    queryKey: ["dataset", id],
    queryFn: () => datasetsApi.get(id),
    enabled: Boolean(id),
    staleTime: 60_000,
  });

  const crumbs = [{ label: "Overview", to: "/" }];
  if (location.pathname.startsWith("/datasets")) {
    crumbs.push({ label: "Datasets", to: "/datasets" });
  } else if (id) {
    crumbs.push({ label: "Datasets", to: "/datasets" });
    crumbs.push({ label: dataset?.filename || "Workspace", to: null });
  }

  return (
    <nav aria-label="Breadcrumb" className="min-w-0">
      <ol className="flex min-w-0 items-center gap-1.5 text-base">
        {crumbs.map((crumb, index) => {
          const last = index === crumbs.length - 1;
          return (
            <li key={`${crumb.label}-${index}`} className="flex min-w-0 items-center gap-1.5">
              {index > 0 && (
                <ChevronLeft size={13} className="shrink-0 rotate-180 text-subtle" aria-hidden="true" />
              )}
              {crumb.to && !last ? (
                <Link
                  to={crumb.to}
                  className="shrink-0 text-muted transition-colors hover:text-ink focus-visible:ring-2 focus-visible:ring-accent/50"
                >
                  {crumb.label}
                </Link>
              ) : (
                <span
                  className="truncate font-medium text-ink"
                  aria-current={last ? "page" : undefined}
                >
                  {crumb.label}
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
