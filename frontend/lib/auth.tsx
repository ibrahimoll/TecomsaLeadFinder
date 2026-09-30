"use client";

import { createContext, useContext } from "react";

import type { Me } from "@/types";

export const AuthContext = createContext<Me | null>(null);

export function useCurrentUser(): Me {
  const user = useContext(AuthContext);
  if (!user) throw new Error("useCurrentUser must be used inside the authenticated app shell");
  return user;
}

export function isPrivileged(user: Me): boolean {
  return user.role === "ADMIN" || user.role === "SALES_MANAGER";
}
