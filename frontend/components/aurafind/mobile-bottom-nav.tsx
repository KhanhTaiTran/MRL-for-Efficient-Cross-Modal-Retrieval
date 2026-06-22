"use client";

import clsx from "clsx";
import { Home, Search, ShoppingBag, User } from "lucide-react";

export type MobileNavTab = "home" | "search" | "cart" | "profile";

interface MobileBottomNavProps {
  activeTab: MobileNavTab;
  cartCount: number;
  onHome: () => void;
  onSearch: () => void;
  onCart: () => void;
  onProfile: () => void;
}

export function MobileBottomNav({
  activeTab,
  cartCount,
  onHome,
  onSearch,
  onCart,
  onProfile,
}: MobileBottomNavProps) {
  const items: {
    id: MobileNavTab;
    label: string;
    icon: typeof Home;
    onClick: () => void;
    badge?: number;
  }[] = [
    { id: "home", label: "Home", icon: Home, onClick: onHome },
    { id: "search", label: "Search", icon: Search, onClick: onSearch },
    {
      id: "cart",
      label: "Cart",
      icon: ShoppingBag,
      onClick: onCart,
      badge: cartCount,
    },
    { id: "profile", label: "Profile", icon: User, onClick: onProfile },
  ];

  return (
    <nav
      aria-label="Mobile navigation"
      className="fixed inset-x-0 bottom-0 z-50 border-t border-neutral-200/80 bg-white/90 pb-[env(safe-area-inset-bottom)] backdrop-blur-xl md:hidden dark:border-neutral-800 dark:bg-neutral-950/90"
    >
      <div className="mx-auto flex max-w-lg items-stretch justify-around px-2 py-2">
        {items.map(({ id, label, icon: Icon, onClick, badge }) => {
          const isActive = activeTab === id;
          return (
            <button
              key={id}
              type="button"
              onClick={onClick}
              className={clsx(
                "relative flex min-w-[64px] flex-1 flex-col items-center gap-1 rounded-xl px-2 py-2 transition-colors",
                isActive
                  ? "text-neutral-900 dark:text-white"
                  : "text-neutral-400 hover:text-neutral-600 dark:hover:text-neutral-300",
              )}
            >
              <span className="relative">
                <Icon
                  className={clsx("h-5 w-5", isActive && "stroke-[2.5]")}
                />
                {badge !== undefined && badge > 0 && (
                  <span className="absolute -right-2 -top-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-neutral-900 px-1 text-[9px] font-bold text-white dark:bg-white dark:text-neutral-900">
                    {badge}
                  </span>
                )}
              </span>
              <span className="text-[10px] font-medium">{label}</span>
              {isActive && (
                <span className="absolute -bottom-0.5 h-0.5 w-6 rounded-full bg-neutral-900 dark:bg-white" />
              )}
            </button>
          );
        })}
      </div>
    </nav>
  );
}
