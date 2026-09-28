"use client";

import { createContext, useContext } from "react";

import type { User } from "@/types";

export const AuthContext = createContext<User | null>(null);

export function useCurrentUser(): User {
  const user = useContext(AuthContext);
  if (!user) throw new Error("useCurrentUser must be used inside the authenticated app shell");
  return user;
}

export function isPrivileged(user: User): boolean {
  return user.role === "ADMIN" || user.role === "SALES_MANAGER";
}
