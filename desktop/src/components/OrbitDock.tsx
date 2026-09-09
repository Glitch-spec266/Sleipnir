import {
  AudioLines,
  CircleDotDashed,
  History,
  Home,
  MessagesSquare,
  Route,
  ScanSearch,
  Settings,
  ShieldCheck,
} from "lucide-react";
import type { AppSettings } from "../domain/types";

export type ViewId =
  | "home"
  | "run"
  | "review"
  | "voice"
  | "console"
  | "chronicle"
  | "routing"
  | "trust"
  | "settings";

const simpleItems: Array<{ id: ViewId; label: string; icon: typeof Home }> = [
  { id: "home", label: "Home", icon: Home },
  { id: "run", label: "Run", icon: CircleDotDashed },
  { id: "review", label: "Review", icon: ScanSearch },
  { id: "voice", label: "Voice", icon: AudioLines },
];

const advancedItems: Array<{ id: ViewId; label: string; icon: typeof Home; module?: keyof AppSettings["advancedModules"] }> = [
  { id: "console", label: "Console", icon: MessagesSquare, module: "tools" },
  { id: "chronicle", label: "Chronicle", icon: History, module: "chronicle" },
  { id: "routing", label: "Routing", icon: Route, module: "helm" },
  { id: "trust", label: "Trust", icon: ShieldCheck, module: "audit" },
  { id: "settings", label: "Settings", icon: Settings },
];

interface OrbitDockProps {
  active: ViewId;
  advanced: boolean;
  modules?: AppSettings["advancedModules"];
  onNavigate: (view: ViewId) => void;
}

export function OrbitDock({ active, advanced, modules, onNavigate }: OrbitDockProps) {
  const visibleAdvanced = advancedItems.filter((item) => !item.module || modules?.[item.module] !== false);
  const items = advanced ? [...simpleItems, ...visibleAdvanced] : simpleItems;

  return (
    <nav className="dock" aria-label="Workspace">
      {items.map(({ id, label, icon: Icon }) => (
        <button
          key={id}
          type="button"
          aria-current={active === id ? "page" : undefined}
          aria-label={label}
          onClick={() => onNavigate(id)}
        >
          <Icon size={16} aria-hidden="true" />
          <span>{label}</span>
        </button>
      ))}
    </nav>
  );
}
