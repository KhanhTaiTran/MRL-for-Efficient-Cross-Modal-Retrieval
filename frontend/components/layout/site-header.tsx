"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Menu, MenuButton, MenuItem, MenuItems } from "@headlessui/react";
import {
  Check,
  Heart,
  LogOut,
  Monitor,
  Moon,
  Package,
  Settings,
  ShoppingBag,
  Sun,
  User,
} from "lucide-react";
import { useAuth } from "components/auth/auth-provider";
import { SearchPanel } from "components/aurafind/search-panel";
import { useSearch } from "components/aurafind/search-provider";
import { getCart } from "lib/api/commerce";
import { signOut } from "lib/api/client";
import { useTheme } from "./theme-provider";

const iconButton =
  "relative inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full border border-neutral-200 text-neutral-700 transition hover:bg-neutral-100 dark:border-neutral-700 dark:text-neutral-200 dark:hover:bg-neutral-800";
const menuItems =
  "z-[80] mt-3 w-60 rounded-xl border border-neutral-200 bg-white p-2 text-sm text-neutral-900 shadow-lg focus:outline-none dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-100";
const menuLink =
  "flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left data-focus:bg-neutral-100 dark:data-focus:bg-neutral-800";

export function SiteHeader() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const {
    query,
    setQuery,
    selected,
    selectImage,
    clearImage,
    submit,
    loading,
    error,
  } = useSearch();
  const { theme, setTheme } = useTheme();
  const [focused, setFocused] = useState(false);
  const [cart, setCart] = useState({ owner: "", count: 0 });
  const [signingOut, setSigningOut] = useState(false);
  const [accountError, setAccountError] = useState("");
  useEffect(() => {
    if (!user) {
      setCart({ owner: "", count: 0 });
      return;
    }
    let alive = true;
    let revision = 0;
    const update = () => {
      const id = ++revision;
      getCart()
        .then(({ data }) => {
          if (alive && id === revision)
            setCart({
              owner: user.id,
              count: data.items.reduce((sum, item) => sum + item.quantity, 0),
            });
        })
        .catch(() => {});
    };
    update();
    window.addEventListener("focus", update);
    window.addEventListener("aurafind-cart-updated", update);
    return () => {
      alive = false;
      window.removeEventListener("focus", update);
      window.removeEventListener("aurafind-cart-updated", update);
    };
  }, [user?.id]);
  const cartCount = cart.owner === user?.id ? cart.count : 0;
  const searchProps = {
    query,
    onQueryChange: setQuery,
    onTextSearch: submit,
    onImageSelect: selectImage,
    onDropImage: selectImage,
    onClearImage: clearImage,
    imagePreview: selected?.preview ?? null,
    imageFileName: selected?.file.name ?? null,
    isImageMode: !!selected,
    onImageModeChange: (image: boolean) => {
      if (!image) clearImage();
    },
    isLoading: loading,
    searchFocused: focused,
    onSearchFocusChange: setFocused,
  };
  const accountLinks = user
    ? [
        { href: "/account", label: "My account", icon: User },
        { href: "/account/orders", label: "My orders", icon: Package },
        { href: "/wishlist", label: "Saved items", icon: Heart },
        ...(user.role === "admin"
          ? [{ href: "/admin", label: "Administration", icon: Settings }]
          : []),
      ]
    : [
        { href: "/login", label: "Sign in", icon: User },
        { href: "/register", label: "Create an account", icon: User },
      ];
  return (
    <header className="sticky top-0 z-50 border-b border-neutral-200 bg-neutral-50/95 backdrop-blur-xl dark:border-neutral-800 dark:bg-neutral-950/95">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[90] focus:rounded-lg focus:bg-white focus:px-4 focus:py-3 focus:text-neutral-900"
      >
        Skip to content
      </a>
      <div className="site-container flex flex-wrap items-center gap-x-3 gap-y-3 py-3 sm:gap-x-4 lg:flex-nowrap">
        <Link
          href="/"
          className="flex shrink-0 items-center gap-2.5"
          aria-label="AuraFind home"
        >
          <span className="h-9 w-9 overflow-hidden rounded-lg border border-neutral-200 bg-white">
            <Image
              src="/logo-aurafind.png"
              alt=""
              width={36}
              height={36}
              className="h-full w-full object-contain p-1"
              priority
            />
          </span>
          <span className="hidden text-sm font-semibold tracking-[0.18em] uppercase min-[360px]:inline">
            AuraFind
          </span>
        </Link>
        <Link
          href="/search"
          aria-current={pathname.startsWith("/search") ? "page" : undefined}
          className={`ml-1 hidden rounded-lg px-2 py-2 text-sm font-medium sm:inline-flex ${pathname.startsWith("/search") ? "text-neutral-950 underline underline-offset-8 dark:text-white" : "text-neutral-500 hover:text-neutral-950 dark:hover:text-white"}`}
        >
          Shop
        </Link>
        <div className="order-last min-w-0 basis-full lg:order-none lg:mx-auto lg:max-w-2xl lg:flex-1 lg:basis-auto">
          <SearchPanel {...searchProps} compact className="w-full" />
          {error && !pathname.startsWith("/discover") && (
            <p
              role="alert"
              className="mt-1 text-xs text-red-600 dark:text-red-300"
            >
              {error}
            </p>
          )}
        </div>
        <div className="ml-auto flex shrink-0 items-center gap-2">
          <Menu>
            <MenuButton className={iconButton} aria-label="Choose theme">
              <Sun className="h-4 w-4 dark:hidden" />
              <Moon className="hidden h-4 w-4 dark:block" />
            </MenuButton>
            <MenuItems anchor="bottom end" className={menuItems}>
              <p className="px-3 py-2 text-xs font-medium text-neutral-500">
                Appearance
              </p>
              {(
                [
                  { value: "light", label: "Light", icon: Sun },
                  { value: "dark", label: "Dark", icon: Moon },
                  { value: "system", label: "System", icon: Monitor },
                ] as const
              ).map((item) => (
                <MenuItem key={item.value}>
                  <button
                    className={menuLink}
                    onClick={() => setTheme(item.value)}
                  >
                    <item.icon className="h-4 w-4" />
                    {item.label}
                    {theme === item.value && (
                      <Check className="ml-auto h-4 w-4" />
                    )}
                  </button>
                </MenuItem>
              ))}
            </MenuItems>
          </Menu>
          <Link
            href="/cart"
            className={iconButton}
            aria-label={`Shopping cart${cartCount ? `, ${cartCount} items` : ""}`}
          >
            <ShoppingBag className="h-4 w-4" />
            {cartCount > 0 && (
              <span className="absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-neutral-900 px-1 text-[10px] font-semibold text-white dark:bg-white dark:text-neutral-900">
                {cartCount > 99 ? "99+" : cartCount}
              </span>
            )}
          </Link>
          <Menu>
            <MenuButton
              className={iconButton}
              aria-label="User profile"
              disabled={authLoading}
            >
              <User className="h-4 w-4" />
            </MenuButton>
            <MenuItems anchor="bottom end" className={menuItems}>
              <p className="truncate border-b border-neutral-100 px-3 py-3 font-medium dark:border-neutral-800">
                {user ? user.name : "Welcome to AuraFind"}
              </p>
              <MenuItem>
                <Link className={`${menuLink} sm:hidden`} href="/search">
                  <ShoppingBag className="h-4 w-4" />
                  Shop all products
                </Link>
              </MenuItem>
              {accountLinks.map((item) => (
                <MenuItem key={item.href}>
                  <Link className={menuLink} href={item.href}>
                    <item.icon className="h-4 w-4" />
                    {item.label}
                  </Link>
                </MenuItem>
              ))}
              {user && (
                <MenuItem>
                  <button
                    className={`${menuLink} mt-1 border-t border-neutral-100 dark:border-neutral-800`}
                    disabled={signingOut}
                    onClick={async () => {
                      setSigningOut(true);
                      setAccountError("");
                      try {
                        await signOut();
                        router.push("/");
                      } catch {
                        setAccountError(
                          "Could not sign out. Please try again.",
                        );
                      } finally {
                        setSigningOut(false);
                      }
                    }}
                  >
                    <LogOut className="h-4 w-4" />
                    {signingOut ? "Signing out…" : "Sign out"}
                  </button>
                </MenuItem>
              )}
            </MenuItems>
          </Menu>
        </div>
      </div>
      {accountError && (
        <p role="alert" className="site-container pb-2 text-sm text-red-600">
          {accountError}
        </p>
      )}
    </header>
  );
}
