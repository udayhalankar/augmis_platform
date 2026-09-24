"use client";

import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";

import api from "@/lib/api";

import {
  clearAccessToken,
  getAccessToken,
  setAccessToken,
} from "@/lib/auth-storage";


export type AuthUser = {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  status: string;
};


type AuthContextType = {
  user: AuthUser | null;
  loading: boolean;

  login: (
    email: string,
    password: string
  ) => Promise<void>;

  logout: () => void;

  refreshUser: () => Promise<void>;
};


const AuthContext =
  createContext<
    AuthContextType | undefined
  >(undefined);


export function AuthProvider({
  children,
}: {
  children: ReactNode;
}) {

  const [
    user,
    setUser,
  ] = useState<AuthUser | null>(
    null
  );

  const [
    loading,
    setLoading,
  ] = useState(true);


  const logout = useCallback(
    () => {

      clearAccessToken();

      setUser(null);

    },
    []
  );


  const refreshUser =
    useCallback(
      async () => {

        const token =
          getAccessToken();

        if (!token) {

          setUser(null);

          setLoading(false);

          return;
        }

        try {

          const response =
            await api.get<AuthUser>(
              "/api/v1/auth/me"
            );

          setUser(
            response.data
          );

        } catch {

          logout();

        } finally {

          setLoading(false);
        }

      },
      [logout]
    );


  const login = async (
    email: string,
    password: string
  ) => {

    const response =
      await api.post(
        "/api/v1/auth/login",
        {
          email,
          password,
        }
      );

    setAccessToken(
      response.data.access_token
    );

    const me =
      await api.get<AuthUser>(
        "/api/v1/auth/me"
      );

    setUser(
      me.data
    );
  };


  useEffect(
    () => {

      refreshUser();

    },
    [refreshUser]
  );


  useEffect(
    () => {

      const handleExpired =
        () => {

          logout();

        };

      window.addEventListener(
        "augmis-auth-expired",
        handleExpired
      );

      return () => {

        window.removeEventListener(
          "augmis-auth-expired",
          handleExpired
        );
      };

    },
    [logout]
  );


  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        login,
        logout,
        refreshUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}


export function useAuth() {

  const context =
    useContext(AuthContext);

  if (!context) {

    throw new Error(
      "useAuth must be used inside AuthProvider"
    );
  }

  return context;
}