import axios from "axios";

import {
  clearAccessToken,
  getAccessToken,
} from "@/lib/auth-storage";


const apiBaseUrl =
  process.env.NEXT_PUBLIC_API_BASE_URL ??
  "http://127.0.0.1:8000";


export const api = axios.create({
  baseURL: apiBaseUrl,
});


api.interceptors.request.use(
  (config) => {

    const token =
      getAccessToken();

    if (token) {

      config.headers.Authorization =
        `Bearer ${token}`;
    }

    return config;
  }
);


api.interceptors.response.use(
  (response) => response,

  (error) => {

    if (
      error.response?.status === 401
    ) {

      clearAccessToken();

      if (
        typeof window !== "undefined"
      ) {

        window.dispatchEvent(
          new Event(
            "augmis-auth-expired"
          )
        );
      }
    }

    return Promise.reject(error);
  }
);


export default api;