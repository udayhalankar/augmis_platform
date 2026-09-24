const ACCESS_TOKEN_KEY =
  "augmis_access_token";

export function getAccessToken():
  string | null {

  if (typeof window === "undefined") {
    return null;
  }

  return sessionStorage.getItem(
    ACCESS_TOKEN_KEY
  );
}


export function setAccessToken(
  token: string
): void {

  if (typeof window === "undefined") {
    return;
  }

  sessionStorage.setItem(
    ACCESS_TOKEN_KEY,
    token
  );
}


export function clearAccessToken():
  void {

  if (typeof window === "undefined") {
    return;
  }

  sessionStorage.removeItem(
    ACCESS_TOKEN_KEY
  );
}