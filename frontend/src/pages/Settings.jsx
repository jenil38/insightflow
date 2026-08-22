/**
 * Workspace settings.
 *
 * Three tiers of setting live here, and the difference matters:
 *
 * 1. APPEARANCE settings apply immediately and persist through ThemeProvider,
 *    which writes them onto <html> for the CSS in index.css to act on. They
 *    have no save button because there is nothing to submit - the preview is
 *    the product.
 *
 * 2. WORKSPACE preferences (notifications, privacy, exports, assistant) are
 *    held as draft state and committed on save, so a half-changed form can be
 *    abandoned. They persist to localStorage; there is no server endpoint for
 *    them yet.
 *
 * 3. ACCOUNT actions that do have a backend - password reset, sign out - call
 *    it for real.
 *
 * Sections describing plan, team, integrations and API keys are presentational:
 * the API has no corresponding endpoints, so they render representative state
 * rather than inventing calls that would fail.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import clsx from "clsx";
import {
  AlertTriangle, Bell, Building2, Check, Copy, CreditCard, Database, Download,
  ExternalLink, Eye, KeyRound, Loader2, Lock, LogOut, Mail, Monitor, Moon,
  Palette, Plug, Plus, RefreshCw, Shield, Sparkles, Sun, Trash2, User, Users,
} from "lucide-react";

import { errorMessage } from "../api/client.js";
import { auth as authApi } from "../api/endpoints.js";
import { useAuth, useTheme } from "../app/providers.jsx";
import {
  Alert, Badge, Button, Card, CardBody, CardHeader, ConfirmDialog, Field,
  IconButton, Input, PageHeader, SegmentedControl, Select, Slider, Toggle,
  Tooltip,
} from "../components/ui/index.jsx";

/* ------------------------------------------------------------------ config */

const SECTIONS = [
  { key: "profile", label: "Profile", icon: User },
  { key: "security", label: "Security", icon: Shield },
  { key: "appearance", label: "Appearance", icon: Palette },
  { key: "notifications", label: "Notifications", icon: Bell },
  { key: "privacy", label: "Data & privacy", icon: Database },
  { key: "assistant", label: "AI assistant", icon: Sparkles },
  { key: "exports", label: "Exports", icon: Download },
  { key: "integrations", label: "Integrations", icon: Plug },
  { key: "team", label: "Team", icon: Users },
  { key: "keys", label: "API keys", icon: KeyRound },
  { key: "billing", label: "Plan & billing", icon: CreditCard },
  { key: "danger", label: "Danger zone", icon: AlertTriangle },
];

const PREFS_KEY = "if_workspace_prefs";

const PREF_DEFAULTS = {
  // Notifications
  notifyTrainingComplete: true,
  notifyQualityDrops: true,
  notifyDriftDetected: true,
  notifyWeeklyDigest: false,
  notifyProductUpdates: false,
  notifyChannel: "email",
  qualityThreshold: 70,

  // Data and privacy
  retentionDays: "365",
  shareDiagnostics: true,
  maskPiiInPreviews: true,
  allowSampleInPrompts: true,

  // Assistant
  assistantVerbosity: "balanced",
  assistantAutoSuggest: true,
  assistantCiteColumns: true,
  assistantTemperature: 20,

  // Exports
  exportFormat: "csv",
  exportIncludeCleaned: true,
  exportIncludeMetadata: true,
  reportBranding: true,
};

function readPrefs() {
  try {
    return { ...PREF_DEFAULTS, ...JSON.parse(localStorage.getItem(PREFS_KEY) || "{}") };
  } catch {
    return { ...PREF_DEFAULTS };
  }
}

/* ------------------------------------------------------------------- page */

export default function Settings() {
  const [section, setSection] = useState("profile");
  const { user } = useAuth();

  // Saved is the committed state; draft is what the form is editing. Comparing
  // the two is what drives the unsaved-changes bar, so no component has to
  // track dirtiness field by field.
  const [saved, setSaved] = useState(readPrefs);
  const [draft, setDraft] = useState(saved);
  const [saving, setSaving] = useState(false);

  const dirty = useMemo(
    () => JSON.stringify(saved) !== JSON.stringify(draft),
    [saved, draft],
  );

  const set = (patch) => setDraft((current) => ({ ...current, ...patch }));

  // Warn before a reload or tab close drops uncommitted edits. Registered only
  // while dirty so the browser doesn't prompt on every navigation.
  useEffect(() => {
    if (!dirty) return undefined;
    const onBeforeUnload = (event) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);

  async function save() {
    setSaving(true);
    try {
      localStorage.setItem(PREFS_KEY, JSON.stringify(draft));
      setSaved(draft);
      toast.success("Preferences saved");
    } catch {
      toast.error("Could not save preferences. Local storage may be full.");
    } finally {
      setSaving(false);
    }
  }

  const shared = { prefs: draft, set };

  return (
    <div className="pb-24">
      <PageHeader
        title="Settings"
        description="Manage your profile, workspace appearance, data controls, and team access."
        meta={
          <>
            <span className="inline-flex items-center gap-1.5">
              <Building2 size={13} aria-hidden="true" />
              Acme Analytics
            </span>
            <span>{user?.email}</span>
            <Badge tone="accent">Growth plan</Badge>
          </>
        }
      />

      <div className="flex flex-col gap-6 lg:flex-row lg:gap-8">
        <SectionNav value={section} onChange={setSection} />

        <div className="min-w-0 flex-1">
          <div className="mx-auto max-w-3xl space-y-5">
            {section === "profile" && <ProfileSection user={user} />}
            {section === "security" && <SecuritySection user={user} />}
            {section === "appearance" && <AppearanceSection />}
            {section === "notifications" && <NotificationsSection {...shared} />}
            {section === "privacy" && <PrivacySection {...shared} />}
            {section === "assistant" && <AssistantSection {...shared} />}
            {section === "exports" && <ExportsSection {...shared} />}
            {section === "integrations" && <IntegrationsSection />}
            {section === "team" && <TeamSection user={user} />}
            {section === "keys" && <ApiKeysSection />}
            {section === "billing" && <BillingSection />}
            {section === "danger" && <DangerSection />}
          </div>
        </div>
      </div>

      <SaveBar
        visible={dirty}
        saving={saving}
        onSave={save}
        onCancel={() => setDraft(saved)}
      />
    </div>
  );
}

/* --------------------------------------------------------------- nav rail */

function SectionNav({ value, onChange }) {
  const active = SECTIONS.find((s) => s.key === value);

  return (
    <>
      {/* Mobile and tablet: a select is the right control for twelve options in
          a narrow column - a scrolling pill rail hides most of them. */}
      <div className="lg:hidden">
        <Field label="Section" htmlFor="settings-section">
          <Select
            id="settings-section"
            value={value}
            onChange={(event) => onChange(event.target.value)}
            options={SECTIONS.map((s) => ({ value: s.key, label: s.label }))}
          />
        </Field>
      </div>

      <nav aria-label="Settings sections" className="hidden w-56 shrink-0 lg:block">
        <div className="sticky top-20 space-y-0.5">
          {SECTIONS.map((item) => {
            const selected = item.key === value;
            const danger = item.key === "danger";
            return (
              <button
                key={item.key}
                type="button"
                onClick={() => onChange(item.key)}
                aria-current={selected ? "page" : undefined}
                className={clsx(
                  "flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-base transition-colors",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50",
                  selected && !danger && "bg-accent-soft font-medium text-accent",
                  selected && danger && "bg-danger-soft font-medium text-danger",
                  !selected && danger && "text-danger/80 hover:bg-danger-soft hover:text-danger",
                  !selected && !danger && "text-muted hover:bg-surface hover:text-ink",
                )}
              >
                <item.icon size={15} className="shrink-0" aria-hidden="true" />
                <span className="truncate">{item.label}</span>
              </button>
            );
          })}
        </div>
      </nav>

      {/* Announce section changes for screen readers on every breakpoint. */}
      <span className="sr-only" role="status">{active?.label} settings</span>
    </>
  );
}

/* ---------------------------------------------------------------- save bar */

function SaveBar({ visible, saving, onSave, onCancel }) {
  if (!visible) return null;
  return (
    <div
      role="region"
      aria-label="Unsaved changes"
      className="fixed inset-x-0 bottom-0 z-30 animate-slide-up border-t border-line
                 bg-surface/95 px-4 py-3 backdrop-blur sm:px-6"
    >
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-center justify-between gap-3">
        <p className="flex items-center gap-2 text-base text-ink">
          <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-warning" aria-hidden="true" />
          You have unsaved changes
        </p>
        <div className="flex items-center gap-2">
          <Button variant="secondary" onClick={onCancel} disabled={saving}>
            Discard
          </Button>
          <Button onClick={onSave} loading={saving} icon={Check}>
            Save changes
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ shared bits */

/** A labelled row with a control on the right. The workhorse of this page. */
function Row({ label, description, children, className }) {
  return (
    <div className={clsx("flex flex-wrap items-start justify-between gap-3 py-1", className)}>
      <div className="min-w-0 flex-1">
        <p className="text-base text-ink">{label}</p>
        {description && <p className="mt-0.5 text-xs text-muted">{description}</p>}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

function Divider() {
  return <div className="rule-fade my-1" role="presentation" />;
}

/* ----------------------------------------------------------------- profile */

function ProfileSection({ user }) {
  const [fullName, setFullName] = useState(user?.full_name || "");
  const [role, setRole] = useState("Analytics lead");
  const [timezone, setTimezone] = useState("Europe/London");

  const initials = (user?.full_name || user?.email || "?")
    .split(/[\s@.]+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");

  return (
    <>
      <Card>
        <CardHeader
          title="Profile"
          description="How you appear to other members of this workspace."
        />
        <CardBody className="space-y-5">
          <div className="flex flex-wrap items-center gap-4">
            <span
              className="flex h-16 w-16 shrink-0 items-center justify-center rounded-full
                         bg-accent-soft text-xl font-semibold text-accent shadow-rim"
              aria-hidden="true"
            >
              {initials}
            </span>
            <div className="min-w-0">
              <div className="flex flex-wrap gap-2">
                <Button variant="secondary" size="sm">Upload photo</Button>
                <Button variant="ghost" size="sm">Remove</Button>
              </div>
              <p className="mt-1.5 text-xs text-muted">
                PNG or JPG, up to 2 MB. Square images work best.
              </p>
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Full name" htmlFor="profile-name">
              <Input
                id="profile-name"
                value={fullName}
                onChange={(event) => setFullName(event.target.value)}
                placeholder="Your name"
              />
            </Field>
            <Field
              label="Email"
              htmlFor="profile-email"
              hint="Used for sign-in and workspace notifications."
            >
              <Input id="profile-email" type="email" value={user?.email || ""} readOnly />
            </Field>
            <Field label="Job title" htmlFor="profile-role">
              <Input
                id="profile-role"
                value={role}
                onChange={(event) => setRole(event.target.value)}
              />
            </Field>
            <Field label="Time zone" htmlFor="profile-tz" hint="Report schedules use this.">
              <Select
                id="profile-tz"
                value={timezone}
                onChange={(event) => setTimezone(event.target.value)}
                options={[
                  { value: "Europe/London", label: "London (GMT+0)" },
                  { value: "Europe/Berlin", label: "Berlin (GMT+1)" },
                  { value: "America/New_York", label: "New York (GMT-5)" },
                  { value: "America/Los_Angeles", label: "Los Angeles (GMT-8)" },
                  { value: "Asia/Kolkata", label: "Kolkata (GMT+5:30)" },
                  { value: "Asia/Singapore", label: "Singapore (GMT+8)" },
                ]}
              />
            </Field>
          </div>

          {!user?.is_verified && (
            <Alert tone="warning" title="Email not verified">
              Verify your email to enable scheduled report delivery and password recovery.
            </Alert>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Workspace" description="Shared by everyone on your team." />
        <CardBody className="space-y-4">
          <Field label="Workspace name" htmlFor="workspace-name">
            <Input id="workspace-name" defaultValue="Acme Analytics" />
          </Field>
          <Field
            label="Default dataset visibility"
            htmlFor="workspace-visibility"
            hint="Applies to newly uploaded datasets. Existing datasets keep their current setting."
          >
            <Select
              id="workspace-visibility"
              defaultValue="team"
              options={[
                { value: "private", label: "Private — only me" },
                { value: "team", label: "Team — anyone in this workspace" },
                { value: "org", label: "Organisation — all workspaces" },
              ]}
            />
          </Field>
        </CardBody>
      </Card>
    </>
  );
}

/* ---------------------------------------------------------------- security */

function SecuritySection({ user }) {
  const { logout } = useAuth();
  const [confirmSignOut, setConfirmSignOut] = useState(false);

  const reset = useMutation({
    mutationFn: () => authApi.requestPasswordReset(user?.email),
    onSuccess: () =>
      toast.success("Password reset link sent. Check your inbox."),
    onError: (error) =>
      toast.error(errorMessage(error, "Could not send the reset link.")),
  });

  const sessions = [
    { id: 1, device: "Chrome on Windows", location: "London, United Kingdom", last: "Active now", current: true },
    { id: 2, device: "Safari on macOS", location: "London, United Kingdom", last: "2 hours ago", current: false },
    { id: 3, device: "InsightFlow CLI", location: "eu-west-1 · CI runner", last: "Yesterday", current: false },
  ];

  return (
    <>
      <Card>
        <CardHeader title="Password" description="Change the password used to sign in." />
        <CardBody>
          <Row
            label="Reset password"
            description={`We'll email a secure, single-use link to ${user?.email || "your address"}. It expires in one hour.`}
          >
            <Button
              variant="secondary"
              icon={Mail}
              loading={reset.isPending}
              onClick={() => reset.mutate()}
            >
              Send reset link
            </Button>
          </Row>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Two-factor authentication"
          description="Require a second factor when signing in from a new device."
        />
        <CardBody className="space-y-4">
          <Alert tone="warning" title="Two-factor is not enabled">
            Your workspace holds connected warehouse credentials. Enabling a second factor is
            strongly recommended for accounts with export permissions.
          </Alert>
          <div className="flex flex-wrap gap-2">
            <Button icon={Lock}>Set up authenticator app</Button>
            <Button variant="secondary">Use a security key</Button>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Active sessions"
          description="Devices currently signed in to this account."
          actions={
            <Button variant="danger-ghost" size="sm" onClick={() => setConfirmSignOut(true)}>
              Sign out everywhere
            </Button>
          }
        />
        <CardBody className="space-y-0">
          {sessions.map((session, index) => (
            <div key={session.id}>
              {index > 0 && <Divider />}
              <Row
                label={
                  <span className="flex flex-wrap items-center gap-2">
                    {session.device}
                    {session.current && <Badge tone="success">This device</Badge>}
                  </span>
                }
                description={`${session.location} · ${session.last}`}
              >
                {!session.current && (
                  <Button variant="ghost" size="sm">Revoke</Button>
                )}
              </Row>
            </div>
          ))}
        </CardBody>
      </Card>

      <ConfirmDialog
        open={confirmSignOut}
        onClose={() => setConfirmSignOut(false)}
        onConfirm={async () => {
          await logout();
          toast.success("Signed out on this device.");
        }}
        title="Sign out everywhere?"
        message="This revokes your refresh token and ends the session on this device. Other devices will be signed out the next time their session refreshes."
        confirmLabel="Sign out"
      />
    </>
  );
}

/* -------------------------------------------------------------- appearance */

function AppearanceSection() {
  const { preference, theme, systemTheme, setTheme, appearance, setAppearance, resetAppearance } =
    useTheme();

  return (
    <>
      <Card>
        <CardHeader
          title="Theme"
          description="Applies immediately and is remembered on this device."
        />
        <CardBody className="space-y-4">
          <div
            role="radiogroup"
            aria-label="Colour theme"
            className="grid gap-3 sm:grid-cols-3"
          >
            <ThemeSwatch
              value="light" label="Light" icon={Sun}
              selected={preference === "light"} onSelect={setTheme}
            />
            <ThemeSwatch
              value="dark" label="Dark" icon={Moon}
              selected={preference === "dark"} onSelect={setTheme}
            />
            <ThemeSwatch
              value="system" label="System" icon={Monitor}
              selected={preference === "system"} onSelect={setTheme}
              previewTheme={systemTheme}
              caption={`Following ${systemTheme}`}
            />
          </div>
          <p className="text-xs text-muted">
            {preference === "system"
              ? "InsightFlow follows your operating system and switches automatically when it does."
              : `Locked to ${theme}. Your operating system is currently set to ${systemTheme}.`}
          </p>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Rendering"
          description="Lower settings reduce GPU load on large dashboards and older machines."
          actions={
            <Button variant="ghost" size="sm" icon={RefreshCw} onClick={resetAppearance}>
              Reset
            </Button>
          }
        />
        <CardBody className="space-y-5">
          <Row
            label="3D visual quality"
            description="Controls depth, glass blur and surface lighting across the workspace."
          >
            <SegmentedControl
              label="3D visual quality"
              value={appearance.depth}
              onChange={(depth) => setAppearance({ depth })}
              options={[
                { value: "flat", label: "Flat" },
                { value: "balanced", label: "Balanced" },
                { value: "full", label: "Full" },
              ]}
            />
          </Row>

          <Divider />

          <Row
            label="Animation intensity"
            description="Hover lifts, panel entrances and transitions."
          >
            <SegmentedControl
              label="Animation intensity"
              value={appearance.motion}
              onChange={(motion) => setAppearance({ motion })}
              options={[
                { value: "off", label: "Off" },
                { value: "subtle", label: "Subtle" },
                { value: "full", label: "Full" },
              ]}
            />
          </Row>

          <Divider />

          <Row
            label="Dashboard density"
            description="Compact fits more rows on screen; spacious increases type and padding."
          >
            <SegmentedControl
              label="Dashboard density"
              value={appearance.density}
              onChange={(density) => setAppearance({ density })}
              options={[
                { value: "compact", label: "Compact" },
                { value: "default", label: "Default" },
                { value: "spacious", label: "Spacious" },
              ]}
            />
          </Row>

          {appearance.motion !== "full" || appearance.depth !== "full" ? (
            <Alert tone="info" title="Reduced rendering is active">
              Your system's own reduced-motion setting always takes priority over these controls.
            </Alert>
          ) : null}
        </CardBody>
      </Card>
    </>
  );
}

/**
 * Miniature of the app rendered in the target theme.
 *
 * The preview hard-codes its colours because it has to depict a theme that is
 * not the active one - it is the single place in the app where reading from
 * the live tokens would show the wrong thing.
 */
function ThemeSwatch({ value, label, icon: Icon, selected, onSelect, previewTheme, caption }) {
  const painted = previewTheme || value;
  const dark = painted === "dark";

  const shell = dark ? "#0B0D11" : "#F2F2F0";
  const panel = dark ? "#151920" : "#FCFCFB";
  const line = dark ? "#2E3340" : "#DFE0DE";
  const bar = dark ? "#7EA8DB" : "#183868";
  const dim = dark ? "#3A4150" : "#C4C7C7";

  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={() => onSelect(value)}
      className={clsx(
        "group rounded-xl border p-2 text-left transition-all duration-200",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50",
        selected
          ? "border-accent shadow-focus"
          : "border-line hover:border-line-strong",
      )}
    >
      <div
        className="overflow-hidden rounded-lg border"
        style={{ background: shell, borderColor: line }}
        aria-hidden="true"
      >
        <div className="flex gap-1 p-2">
          <div className="w-1/3 space-y-1 rounded p-1" style={{ background: panel }}>
            <div className="h-1 w-3/4 rounded-full" style={{ background: bar }} />
            <div className="h-1 w-full rounded-full" style={{ background: dim }} />
            <div className="h-1 w-2/3 rounded-full" style={{ background: dim }} />
          </div>
          <div className="flex-1 space-y-1">
            <div className="h-4 rounded p-1" style={{ background: panel }}>
              <div className="h-1 w-1/2 rounded-full" style={{ background: dim }} />
            </div>
            <div className="flex gap-1">
              <div className="h-6 flex-1 rounded" style={{ background: panel }} />
              <div className="h-6 flex-1 rounded" style={{ background: panel }} />
            </div>
            <div className="h-3 rounded" style={{ background: panel }} />
          </div>
        </div>
      </div>

      <div className="mt-2 flex items-center gap-1.5 px-0.5">
        <Icon size={14} className={selected ? "text-accent" : "text-muted"} aria-hidden="true" />
        <span className={clsx("text-base", selected ? "font-medium text-accent" : "text-ink")}>
          {label}
        </span>
        {selected && <Check size={14} className="ml-auto text-accent" aria-hidden="true" />}
      </div>
      {caption && <p className="mt-0.5 px-0.5 text-2xs text-subtle">{caption}</p>}
    </button>
  );
}

/* ----------------------------------------------------------- notifications */

function NotificationsSection({ prefs, set }) {
  return (
    <>
      <Card>
        <CardHeader
          title="Pipeline alerts"
          description="Sent when something finishes, degrades, or needs review."
        />
        <CardBody className="space-y-4">
          <Toggle
            label="Training runs complete"
            description="A model finished training and the leaderboard is ready."
            checked={prefs.notifyTrainingComplete}
            onChange={(v) => set({ notifyTrainingComplete: v })}
          />
          <Divider />
          <Toggle
            label="Data quality drops below threshold"
            description="Triggered when a re-upload scores worse than the limit you set below."
            checked={prefs.notifyQualityDrops}
            onChange={(v) => set({ notifyQualityDrops: v })}
          />
          {prefs.notifyQualityDrops && (
            <div className="rounded-lg bg-canvas p-3">
              <Slider
                label="Quality score threshold"
                min={0}
                max={100}
                step={5}
                value={prefs.qualityThreshold}
                onChange={(qualityThreshold) => set({ qualityThreshold })}
                formatValue={(v) => `${v} / 100`}
                hint="Alert when a dataset's overall quality score falls below this value."
              />
            </div>
          )}
          <Divider />
          <Toggle
            label="Model drift detected"
            description="Live prediction distribution has moved away from the training data."
            checked={prefs.notifyDriftDetected}
            onChange={(v) => set({ notifyDriftDetected: v })}
          />
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Digests and updates" />
        <CardBody className="space-y-4">
          <Toggle
            label="Weekly summary"
            description="Datasets added, models trained, and quality trend across the workspace."
            checked={prefs.notifyWeeklyDigest}
            onChange={(v) => set({ notifyWeeklyDigest: v })}
          />
          <Divider />
          <Toggle
            label="Product updates"
            description="New features and changes to the analysis engine. Roughly monthly."
            checked={prefs.notifyProductUpdates}
            onChange={(v) => set({ notifyProductUpdates: v })}
          />
          <Divider />
          <Row label="Delivery channel" description="Where alerts are sent.">
            <Select
              value={prefs.notifyChannel}
              onChange={(event) => set({ notifyChannel: event.target.value })}
              className="w-44"
              options={[
                { value: "email", label: "Email" },
                { value: "slack", label: "Slack" },
                { value: "both", label: "Email and Slack" },
                { value: "none", label: "In-app only" },
              ]}
            />
          </Row>
        </CardBody>
      </Card>
    </>
  );
}

/* --------------------------------------------------------------- privacy */

function PrivacySection({ prefs, set }) {
  return (
    <>
      <Card>
        <CardHeader
          title="Retention"
          description="How long uploaded data and derived artefacts are kept."
        />
        <CardBody className="space-y-4">
          <Row
            label="Delete datasets after"
            description="Cleaned copies, trained models and reports are removed with the dataset."
          >
            <Select
              value={prefs.retentionDays}
              onChange={(event) => set({ retentionDays: event.target.value })}
              className="w-44"
              options={[
                { value: "30", label: "30 days" },
                { value: "90", label: "90 days" },
                { value: "365", label: "12 months" },
                { value: "never", label: "Keep indefinitely" },
              ]}
            />
          </Row>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Data handling" />
        <CardBody className="space-y-4">
          <Toggle
            label="Mask detected PII in previews"
            description="Columns inferred as email, phone or card numbers render redacted in the data explorer."
            checked={prefs.maskPiiInPreviews}
            onChange={(v) => set({ maskPiiInPreviews: v })}
          />
          <Divider />
          <Toggle
            label="Allow sample rows in Copilot prompts"
            description="The assistant is grounded in computed statistics. Turning this off removes the small sanitised row sample as well, at some cost to answer specificity."
            checked={prefs.allowSampleInPrompts}
            onChange={(v) => set({ allowSampleInPrompts: v })}
          />
          <Divider />
          <Toggle
            label="Share anonymous diagnostics"
            description="Performance and error telemetry. Never includes dataset contents, column names or values."
            checked={prefs.shareDiagnostics}
            onChange={(v) => set({ shareDiagnostics: v })}
          />
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Your data"
          description="Export or remove everything associated with this account."
        />
        <CardBody className="space-y-0">
          <Row
            label="Download an archive"
            description="Datasets, cleaning logs, model metadata and reports as a single ZIP."
          >
            <Button variant="secondary" icon={Download}>Request archive</Button>
          </Row>
          <Divider />
          <Row
            label="Data processing agreement"
            description="Current DPA and the list of sub-processors."
          >
            <Button variant="ghost" icon={ExternalLink}>View</Button>
          </Row>
        </CardBody>
      </Card>
    </>
  );
}

/* -------------------------------------------------------------- assistant */

function AssistantSection({ prefs, set }) {
  return (
    <>
      <Card>
        <CardHeader
          title="Copilot behaviour"
          description="How the assistant answers questions about your datasets."
        />
        <CardBody className="space-y-5">
          <Row label="Answer length" description="Applies to new conversations.">
            <SegmentedControl
              label="Answer length"
              value={prefs.assistantVerbosity}
              onChange={(assistantVerbosity) => set({ assistantVerbosity })}
              options={[
                { value: "concise", label: "Concise" },
                { value: "balanced", label: "Balanced" },
                { value: "detailed", label: "Detailed" },
              ]}
            />
          </Row>

          <Divider />

          <Slider
            label="Response determinism"
            min={0}
            max={100}
            step={10}
            value={prefs.assistantTemperature}
            onChange={(assistantTemperature) => set({ assistantTemperature })}
            formatValue={(v) => (v <= 20 ? "Strict" : v <= 50 ? "Measured" : "Exploratory")}
            hint="Lower values keep answers close to the computed statistics. Higher values allow more interpretation, which increases the risk of over-reaching."
          />

          <Divider />

          <Toggle
            label="Cite the columns used"
            description="Each answer names the columns and metrics it drew on."
            checked={prefs.assistantCiteColumns}
            onChange={(v) => set({ assistantCiteColumns: v })}
          />

          <Divider />

          <Toggle
            label="Suggest questions automatically"
            description="Show starter questions derived from the dataset's actual columns."
            checked={prefs.assistantAutoSuggest}
            onChange={(v) => set({ assistantAutoSuggest: v })}
          />
        </CardBody>
      </Card>

      <Alert tone="info" title="Grounding is not optional">
        The Copilot only answers from statistics InsightFlow computes. It cannot browse the web
        or read datasets outside this workspace, and it will say when something cannot be
        determined rather than estimating.
      </Alert>
    </>
  );
}

/* ---------------------------------------------------------------- exports */

function ExportsSection({ prefs, set }) {
  return (
    <Card>
      <CardHeader
        title="Export defaults"
        description="Pre-selected whenever you download data or generate a report."
      />
      <CardBody className="space-y-4">
        <Row label="Default file format">
          <Select
            value={prefs.exportFormat}
            onChange={(event) => set({ exportFormat: event.target.value })}
            className="w-44"
            options={[
              { value: "csv", label: "CSV" },
              { value: "xlsx", label: "Excel (.xlsx)" },
              { value: "json", label: "JSON" },
              { value: "parquet", label: "Parquet" },
            ]}
          />
        </Row>
        <Divider />
        <Toggle
          label="Export the cleaned copy by default"
          description="When a dataset has been cleaned, download that version rather than the original upload."
          checked={prefs.exportIncludeCleaned}
          onChange={(v) => set({ exportIncludeCleaned: v })}
        />
        <Divider />
        <Toggle
          label="Include run metadata"
          description="Adds a sidecar file recording the random seed, split strategy, library versions and row counts, so a result can be reproduced."
          checked={prefs.exportIncludeMetadata}
          onChange={(v) => set({ exportIncludeMetadata: v })}
        />
        <Divider />
        <Toggle
          label="Workspace branding on PDF reports"
          description="Adds your workspace name and logo to the report cover and footer."
          checked={prefs.reportBranding}
          onChange={(v) => set({ reportBranding: v })}
        />
      </CardBody>
    </Card>
  );
}

/* ----------------------------------------------------------- integrations */

const INTEGRATIONS = [
  { name: "Snowflake", detail: "Warehouse · 14 tables synced", connected: true, tone: "success" },
  { name: "BigQuery", detail: "Warehouse · 3 datasets synced", connected: true, tone: "success" },
  { name: "Amazon S3", detail: "Object storage · eu-west-1", connected: true, tone: "success" },
  { name: "Slack", detail: "Alerts to #data-platform", connected: true, tone: "success" },
  { name: "dbt Cloud", detail: "Import model lineage and tests", connected: false },
  { name: "Looker", detail: "Publish dashboards downstream", connected: false },
  { name: "PagerDuty", detail: "Escalate freshness failures", connected: false },
];

function IntegrationsSection() {
  return (
    <Card>
      <CardHeader
        title="Connected apps"
        description="Sources InsightFlow can read from and destinations it can publish to."
        actions={<Button size="sm" icon={Plus}>Add connection</Button>}
      />
      <CardBody className="space-y-0">
        {INTEGRATIONS.map((item, index) => (
          <div key={item.name}>
            {index > 0 && <Divider />}
            <Row
              label={
                <span className="flex flex-wrap items-center gap-2">
                  {item.name}
                  {item.connected && <Badge tone="success">Connected</Badge>}
                </span>
              }
              description={item.detail}
            >
              <Button variant={item.connected ? "ghost" : "secondary"} size="sm">
                {item.connected ? "Manage" : "Connect"}
              </Button>
            </Row>
          </div>
        ))}
      </CardBody>
    </Card>
  );
}

/* -------------------------------------------------------------------- team */

const ROLES = [
  { value: "owner", label: "Owner" },
  { value: "admin", label: "Admin" },
  { value: "analyst", label: "Analyst" },
  { value: "viewer", label: "Viewer" },
];

function TeamSection({ user }) {
  const [members, setMembers] = useState(() => [
    { id: 1, name: user?.full_name || "You", email: user?.email || "you@acme.com", role: "owner", status: "active" },
    { id: 2, name: "Priya Raman", email: "priya.raman@acme.com", role: "admin", status: "active" },
    { id: 3, name: "Marcus Webb", email: "marcus.webb@acme.com", role: "analyst", status: "active" },
    { id: 4, name: "Sofia Almeida", email: "sofia.almeida@acme.com", role: "analyst", status: "active" },
    { id: 5, name: "Tom Ridley", email: "tom.ridley@acme.com", role: "viewer", status: "invited" },
  ]);

  const setRole = (id, role) =>
    setMembers((list) => list.map((m) => (m.id === id ? { ...m, role } : m)));

  return (
    <>
      <Card>
        <CardHeader
          title="Members"
          description="Roles control who can upload, clean, train and export."
          actions={<Button size="sm" icon={Plus}>Invite member</Button>}
        />
        <CardBody className="space-y-0">
          {members.map((member, index) => (
            <div key={member.id}>
              {index > 0 && <Divider />}
              <div className="flex flex-wrap items-center gap-3 py-1">
                <span
                  className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full
                             bg-accent-soft text-xs font-semibold text-accent"
                  aria-hidden="true"
                >
                  {member.name.split(/\s+/).slice(0, 2).map((p) => p[0]?.toUpperCase()).join("")}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="flex flex-wrap items-center gap-2 text-base text-ink">
                    <span className="truncate">{member.name}</span>
                    {member.status === "invited" && <Badge tone="warning">Invite pending</Badge>}
                  </p>
                  <p className="truncate text-xs text-muted">{member.email}</p>
                </div>
                <div className="flex shrink-0 items-center gap-1.5">
                  {member.role === "owner" ? (
                    <Badge tone="accent">Owner</Badge>
                  ) : (
                    <>
                      <Select
                        aria-label={`Role for ${member.name}`}
                        value={member.role}
                        onChange={(event) => setRole(member.id, event.target.value)}
                        className="w-32"
                        options={ROLES.filter((r) => r.value !== "owner")}
                      />
                      <IconButton
                        icon={Trash2}
                        label={`Remove ${member.name}`}
                        variant="danger-ghost"
                        size="sm"
                      />
                    </>
                  )}
                </div>
              </div>
            </div>
          ))}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="What each role can do" />
        <CardBody>
          <div className="-mx-4 overflow-x-auto px-4">
            <table className="w-full min-w-[34rem] text-base">
              <thead>
                <tr className="border-b border-line text-left">
                  <th scope="col" className="pb-2 pr-3 font-medium text-muted">Permission</th>
                  {ROLES.map((role) => (
                    <th key={role.value} scope="col" className="pb-2 px-2 text-center font-medium text-muted">
                      {role.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[
                  ["View datasets and dashboards", [1, 1, 1, 1]],
                  ["Upload and clean data", [1, 1, 1, 0]],
                  ["Train and compare models", [1, 1, 1, 0]],
                  ["Export data and reports", [1, 1, 1, 0]],
                  ["Manage members and roles", [1, 1, 0, 0]],
                  ["Billing and plan", [1, 0, 0, 0]],
                ].map(([permission, grants]) => (
                  <tr key={permission} className="border-b border-line last:border-0">
                    <th scope="row" className="py-2 pr-3 text-left font-normal text-ink">
                      {permission}
                    </th>
                    {grants.map((granted, i) => (
                      <td key={i} className="px-2 py-2 text-center">
                        {granted ? (
                          <>
                            <Check size={15} className="mx-auto text-success" aria-hidden="true" />
                            <span className="sr-only">Allowed</span>
                          </>
                        ) : (
                          <>
                            <span aria-hidden="true" className="text-subtle">—</span>
                            <span className="sr-only">Not allowed</span>
                          </>
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardBody>
      </Card>
    </>
  );
}

/* ---------------------------------------------------------------- API keys */

function ApiKeysSection() {
  const [keys, setKeys] = useState([
    { id: 1, name: "Production ingest", prefix: "if_live_7Kq2", created: "12 Mar 2026", used: "3 minutes ago" },
    { id: 2, name: "CI test runner", prefix: "if_test_Rb91", created: "28 Jan 2026", used: "Yesterday" },
    { id: 3, name: "Looker sync", prefix: "if_live_Mx48", created: "04 Dec 2025", used: "Never" },
  ]);
  const [revoking, setRevoking] = useState(null);
  const [copied, setCopied] = useState(null);

  // Clear the "copied" tick after a moment, and on unmount so a pending timer
  // can't set state on a gone component.
  const timer = useRef(null);
  useEffect(() => () => clearTimeout(timer.current), []);

  async function copy(item) {
    try {
      await navigator.clipboard.writeText(`${item.prefix}${"•".repeat(24)}`);
      setCopied(item.id);
      clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(null), 2000);
    } catch {
      toast.error("Could not copy. Your browser blocked clipboard access.");
    }
  }

  return (
    <>
      <Card>
        <CardHeader
          title="API keys"
          description="Authenticate programmatic uploads and scheduled report pulls."
          actions={<Button size="sm" icon={Plus}>Create key</Button>}
        />
        <CardBody className="space-y-0">
          {keys.map((item, index) => (
            <div key={item.id}>
              {index > 0 && <Divider />}
              <div className="flex flex-wrap items-center gap-3 py-1">
                <div className="min-w-0 flex-1">
                  <p className="text-base text-ink">{item.name}</p>
                  <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted">
                    <code className="rounded bg-canvas px-1.5 py-0.5 font-mono">
                      {item.prefix}{"•".repeat(8)}
                    </code>
                    <span>Created {item.created}</span>
                    <span aria-hidden="true">·</span>
                    <span>Last used {item.used}</span>
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <Tooltip content={copied === item.id ? "Copied" : "Copy key"}>
                    <IconButton
                      icon={copied === item.id ? Check : Copy}
                      label={copied === item.id ? "Copied" : `Copy ${item.name}`}
                      size="sm"
                      onClick={() => copy(item)}
                    />
                  </Tooltip>
                  <Button variant="danger-ghost" size="sm" onClick={() => setRevoking(item)}>
                    Revoke
                  </Button>
                </div>
              </div>
            </div>
          ))}
        </CardBody>
      </Card>

      <Alert tone="warning" title="Keys are shown once">
        A key's full value is displayed only at creation. If it is lost, revoke it and issue a
        replacement rather than sharing it between services.
      </Alert>

      <ConfirmDialog
        open={Boolean(revoking)}
        onClose={() => setRevoking(null)}
        onConfirm={() => {
          setKeys((list) => list.filter((k) => k.id !== revoking.id));
          toast.success(`"${revoking.name}" revoked`);
        }}
        title={`Revoke "${revoking?.name}"?`}
        message="Any service using this key will start receiving 401 responses immediately. This cannot be undone."
        confirmLabel="Revoke key"
      />
    </>
  );
}

/* ---------------------------------------------------------------- billing */

function BillingSection() {
  return (
    <>
      <Card className="luxe-rim">
        <CardBody className="space-y-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-2xs uppercase tracking-wider text-luxe">Current plan</p>
              <p className="mt-1 text-2xl font-semibold text-ink">Growth</p>
              <p className="mt-0.5 text-base text-muted">
                £490 per month · renews 1 September 2026
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="secondary">Change plan</Button>
              <Button variant="luxe">Upgrade to Enterprise</Button>
            </div>
          </div>

          <div className="rule-luxe" role="presentation" />

          <div className="grid gap-4 sm:grid-cols-3">
            <Meter label="Rows processed" used={2_410_000} limit={5_000_000} format={compact} />
            <Meter label="Models trained" used={148} limit={500} format={(n) => n.toLocaleString()} />
            <Meter label="Seats" used={5} limit={10} format={(n) => String(n)} />
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Payment method" />
        <CardBody>
          <Row label="Visa ending 4021" description="Expires 09 / 2028 · Billing contact: finance@acme.com">
            <Button variant="secondary" size="sm">Update</Button>
          </Row>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Invoices" actions={<Button variant="ghost" size="sm" icon={Download}>Download all</Button>} />
        <CardBody className="space-y-0">
          {[
            ["INV-2026-008", "1 Aug 2026", "£490.00"],
            ["INV-2026-007", "1 Jul 2026", "£490.00"],
            ["INV-2026-006", "1 Jun 2026", "£490.00"],
          ].map(([id, date, amount], index) => (
            <div key={id}>
              {index > 0 && <Divider />}
              <Row label={id} description={date}>
                <div className="flex items-center gap-3">
                  <span className="font-mono text-base tabular-nums text-ink">{amount}</span>
                  <Badge tone="success">Paid</Badge>
                  <IconButton icon={Download} label={`Download ${id}`} size="sm" />
                </div>
              </Row>
            </div>
          ))}
        </CardBody>
      </Card>
    </>
  );
}

function compact(n) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${Math.round(n / 1000)}K`;
  return String(n);
}

function Meter({ label, used, limit, format }) {
  const pct = Math.min(100, Math.round((used / limit) * 100));
  const tone = pct >= 90 ? "bg-danger" : pct >= 75 ? "bg-warning" : "bg-accent";
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-xs text-muted">{label}</p>
        <p className="font-mono text-xs tabular-nums text-subtle">{pct}%</p>
      </div>
      <p className="mt-0.5 text-base text-ink">
        <span className="font-semibold">{format(used)}</span>
        <span className="text-subtle"> / {format(limit)}</span>
      </p>
      <div
        className="surface-inset mt-1.5 h-1.5 overflow-hidden rounded-full"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`${label}: ${pct}% of limit used`}
      >
        <div className={clsx("h-full rounded-full transition-[width] duration-500", tone)} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ danger zone */

function DangerSection() {
  const [confirm, setConfirm] = useState(null);

  return (
    <>
      <Card className="border-danger/40">
        <CardHeader
          title="Danger zone"
          description="These actions are permanent. Read each one before continuing."
        />
        <CardBody className="space-y-0">
          <Row
            label="Clear all analysis results"
            description="Removes every trained model, explanation and report. Uploaded datasets are kept."
          >
            <Button variant="danger-ghost" onClick={() => setConfirm("results")}>
              Clear results
            </Button>
          </Row>
          <Divider />
          <Row
            label="Delete all datasets"
            description="Removes every upload, cleaned copy and the models derived from them."
          >
            <Button variant="danger-ghost" onClick={() => setConfirm("datasets")}>
              Delete datasets
            </Button>
          </Row>
          <Divider />
          <Row
            label="Delete this workspace"
            description="Removes the workspace, its data, and revokes access for all 5 members."
          >
            <Button variant="danger" onClick={() => setConfirm("workspace")}>
              Delete workspace
            </Button>
          </Row>
        </CardBody>
      </Card>

      <ConfirmDialog
        open={confirm === "results"}
        onClose={() => setConfirm(null)}
        onConfirm={() => toast.success("Analysis results cleared")}
        title="Clear all analysis results?"
        message="Every trained model, explanation and generated report will be deleted. Your uploaded datasets and cleaned copies are not affected, so results can be regenerated by re-running training."
        confirmLabel="Clear results"
      />
      <ConfirmDialog
        open={confirm === "datasets"}
        onClose={() => setConfirm(null)}
        onConfirm={() => toast.success("All datasets deleted")}
        title="Delete all datasets?"
        message="This permanently removes every uploaded file, every cleaned copy, and every model trained from them. This cannot be undone."
        confirmLabel="Delete everything"
      />
      <ConfirmDialog
        open={confirm === "workspace"}
        onClose={() => setConfirm(null)}
        onConfirm={() => toast.success("Workspace scheduled for deletion")}
        title="Delete this workspace?"
        message="The workspace, all datasets, models and reports will be permanently deleted, and all 5 members will lose access immediately. Billing stops at the end of the current period."
        confirmLabel="Delete workspace"
      />
    </>
  );
}
