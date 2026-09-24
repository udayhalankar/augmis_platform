





"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

import { useRouter }
  from "next/navigation";

import axios from "axios";

import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  InputAdornment,
  TextField,
  Typography,
} from "@mui/material";

import AppsOutlined
  from "@mui/icons-material/AppsOutlined";

import RefreshOutlined
  from "@mui/icons-material/RefreshOutlined";

import SearchOutlined
  from "@mui/icons-material/SearchOutlined";

import AppShell
  from "@/components/app-shell";

import ProtectedRoute
  from "@/components/protected-route";

import {
  loadMarketplaceOffers,
  MarketplaceOffer,
} from "@/lib/marketplace";

import {
  subscribeTenantToOffer,
} from "@/lib/subscriptions";


const TENANT_STORAGE_KEY =
  "augmis.platform.selectedTenantId";


function formatStatus(
  value: string
): string {

  return String(
    value || ""
  )
    .replace(
      /_/g,
      " "
    )
    .replace(
      /\b\w/g,
      (character) =>
        character.toUpperCase()
    );
}


function entitlementSummary(
  offer:
    MarketplaceOffer
): string {

  const deploy =
    offer.entitlements.find(
      (item) =>
        item.code ===
        "application.deploy"
    );


  const value =
    deploy?.value as
      | {
          maxInstances?: number;
        }
      | null
      | undefined;


  if (
    typeof value?.maxInstances ===
      "number"
  ) {

    return (
      `${value.maxInstances} instance${
        value.maxInstances === 1
          ? ""
          : "s"
      }`
    );
  }


  return (
    "Application deployment"
  );
}


function apiError(
  error: unknown,
  fallback: string
): string {

  if (
    axios.isAxiosError(
      error
    )
  ) {

    const detail =
      error.response?.data
        ?.detail;


    if (
      typeof detail ===
      "string"
    ) {

      return detail;
    }
  }


  if (
    error instanceof Error
  ) {

    return error.message;
  }


  return fallback;
}


export default function MarketplacePage() {

  const router =
    useRouter();


  const [
    offers,
    setOffers,
  ] =
    useState<
      MarketplaceOffer[]
    >([]);


  const [
    loading,
    setLoading,
  ] =
    useState(true);


  const [
    error,
    setError,
  ] =
    useState("");


  const [
    search,
    setSearch,
  ] =
    useState("");


  const [
    subscribeOffer,
    setSubscribeOffer,
  ] =
    useState<
      MarketplaceOffer | null
    >(null);


  const [
    tenantId,
    setTenantId,
  ] =
    useState("");


  const [
    subscribing,
    setSubscribing,
  ] =
    useState(false);


  useEffect(
    () => {

      const saved =
        window.localStorage.getItem(
          TENANT_STORAGE_KEY
        );


      if (
        saved
      ) {

        setTenantId(
          saved
        );
      }

    },
    []
  );


  const loadMarketplace =
    useCallback(
      async () => {

        setLoading(
          true
        );

        setError(
          ""
        );


        try {

          const result =
            await loadMarketplaceOffers();


          setOffers(
            result
          );

        } catch {

          setError(
            "Marketplace offers could not be loaded."
          );

        } finally {

          setLoading(
            false
          );
        }
      },
      []
    );


  useEffect(
    () => {

      loadMarketplace();

    },
    [
      loadMarketplace,
    ]
  );


  const filteredOffers =
    useMemo(
      () => {

        const query =
          search
            .trim()
            .toLowerCase();


        if (!query) {
          return offers;
        }


        return offers.filter(
          (offer) => {

            const text = [
              offer.name,
              offer.description,
              offer.offerKey,

              offer.application
                .name,

              offer.application
                .description,

              offer.application
                .appKey,

              offer.version
                .version,

              offer.version
                .buildType,
            ]
              .filter(Boolean)
              .join(" ")
              .toLowerCase();


            return text.includes(
              query
            );
          }
        );
      },
      [
        offers,
        search,
      ]
    );


  const subscribe =
    async () => {

      if (
        !subscribeOffer
      ) {

        return;
      }


      const cleanTenantId =
        tenantId.trim();


      if (
        !cleanTenantId
      ) {

        setError(
          "Enter the tenant ID that should subscribe to this application."
        );

        return;
      }


      setSubscribing(
        true
      );

      setError(
        ""
      );


      try {

        await subscribeTenantToOffer(
          cleanTenantId,
          subscribeOffer.id
        );


        window.localStorage.setItem(
          TENANT_STORAGE_KEY,
          cleanTenantId
        );


        setSubscribeOffer(
          null
        );


        router.push(
          `/subscriptions?tenantId=${encodeURIComponent(cleanTenantId)}`
        );

      } catch (
        subscribeError
      ) {

        setError(
          apiError(
            subscribeError,
            "Subscription could not be created."
          )
        );

      } finally {

        setSubscribing(
          false
        );
      }
    };


  return (
    <ProtectedRoute>

      <AppShell>

        <Box>

          <Box
            sx={{
              display:
                "flex",

              alignItems:
                "flex-start",

              justifyContent:
                "space-between",

              gap:
                2,

              flexWrap:
                "wrap",

              mb:
                3,
            }}
          >

            <Box>

              <Typography
                sx={{
                  fontSize:
                    12,

                  color:
                    "text.secondary",

                  textTransform:
                    "uppercase",

                  letterSpacing:
                    0.8,

                  mb:
                    0.5,
                }}
              >
                Application Catalog
              </Typography>


              <Typography
                variant="h4"
              >
                Marketplace
              </Typography>


              <Typography
                sx={{
                  mt:
                    0.5,

                  color:
                    "text.secondary",
                }}
              >
                Discover active offers
                backed by published
                application versions.
              </Typography>

            </Box>


            <Button
              variant="outlined"

              startIcon={
                <RefreshOutlined />
              }

              onClick={
                loadMarketplace
              }

              disabled={
                loading
              }
            >
              Refresh
            </Button>

          </Box>


          <Box
            sx={{
              bgcolor:
                "#ffffff",

              border:
                "1px solid",

              borderColor:
                "divider",

              px:
                2.5,

              py:
                2,

              mb:
                2,
            }}
          >

            <TextField
              fullWidth

              size="small"

              placeholder=
                "Search applications or offers"

              value={
                search
              }

              onChange={
                (event) =>
                  setSearch(
                    event.target.value
                  )
              }

              slotProps={{
                input: {
                  startAdornment: (
                    <InputAdornment
                      position="start"
                    >
                      <SearchOutlined
                        fontSize="small"
                      />
                    </InputAdornment>
                  ),
                },
              }}
            />

          </Box>


          {error && (

            <Alert
              severity="error"

              sx={{
                mb:
                  2,
              }}
            >
              {error}
            </Alert>

          )}


          {loading ? (

            <Box
              sx={{
                minHeight:
                  320,

                bgcolor:
                  "#ffffff",

                border:
                  "1px solid",

                borderColor:
                  "divider",

                display:
                  "grid",

                placeItems:
                  "center",
              }}
            >
              <CircularProgress
                size={28}
              />
            </Box>

          ) : filteredOffers.length === 0 ? (

            <Box
              sx={{
                minHeight:
                  280,

                bgcolor:
                  "#ffffff",

                border:
                  "1px solid",

                borderColor:
                  "divider",

                display:
                  "grid",

                placeItems:
                  "center",

                textAlign:
                  "center",

                p:
                  4,
              }}
            >

              <Box>

                <AppsOutlined
                  sx={{
                    fontSize:
                      40,

                    color:
                      "text.secondary",
                  }}
                />


                <Typography
                  sx={{
                    mt:
                      1,

                    fontSize:
                      16,

                    fontWeight:
                      600,
                  }}
                >
                  No marketplace
                  applications
                </Typography>


                <Typography
                  sx={{
                    mt:
                      0.5,

                    fontSize:
                      12,

                    color:
                      "text.secondary",
                  }}
                >
                  Activate an offer for
                  an application that
                  has a published
                  version.
                </Typography>

              </Box>

            </Box>

          ) : (

            <Box
              sx={{
                display:
                  "grid",

                gridTemplateColumns: {
                  xs:
                    "1fr",

                  md:
                    "repeat(2, minmax(0, 1fr))",

                  xl:
                    "repeat(3, minmax(0, 1fr))",
                },

                gap:
                  2,
              }}
            >

              {filteredOffers.map(
                (offer) => (

                  <MarketplaceCard
                    key={
                      offer.id
                    }

                    offer={
                      offer
                    }

                    onSubscribe={
                      () => {

                        setSubscribeOffer(
                          offer
                        );

                        setError(
                          ""
                        );
                      }
                    }
                  />

                )
              )}

            </Box>

          )}

        </Box>


        <Dialog
          open={
            Boolean(
              subscribeOffer
            )
          }

          onClose={
            () => {

              if (
                subscribing
              ) {

                return;
              }


              setSubscribeOffer(
                null
              );
            }
          }

          fullWidth

          maxWidth="sm"
        >

          <DialogTitle>
            Subscribe Tenant
          </DialogTitle>


          <DialogContent>

            <Typography
              sx={{
                mb:
                  0.5,

                fontSize:
                  14,

                fontWeight:
                  600,
              }}
            >
              {subscribeOffer
                ?.application
                .name}
            </Typography>


            <Typography
              sx={{
                mb:
                  2.5,

                fontSize:
                  11.5,

                color:
                  "text.secondary",
              }}
            >
              {subscribeOffer
                ?.name}

              {subscribeOffer
                ? (
                    ` · ${entitlementSummary(
                      subscribeOffer
                    )}`
                  )
                : ""}
            </Typography>


            <TextField
              label="Tenant ID"

              value={
                tenantId
              }

              onChange={
                (event) =>
                  setTenantId(
                    event.target
                      .value
                  )
              }

              fullWidth

              required

              helperText=
                "Temporary Step 3B input. This will be replaced with the platform tenant selector."
            />

          </DialogContent>


          <DialogActions>

            <Button
              disabled={
                subscribing
              }

              onClick={
                () =>
                  setSubscribeOffer(
                    null
                  )
              }
            >
              Cancel
            </Button>


            <Button
              variant="contained"

              disabled={
                subscribing ||
                !tenantId.trim()
              }

              onClick={
                subscribe
              }
            >
              {subscribing
                ? "Subscribing..."
                : "Subscribe"}
            </Button>

          </DialogActions>

        </Dialog>

      </AppShell>

    </ProtectedRoute>
  );
}


function MarketplaceCard({
  offer,
  onSubscribe,
}: {
  offer:
    MarketplaceOffer;

  onSubscribe:
    () => void;
}) {

  return (
    <Box
      sx={{
        bgcolor:
          "#ffffff",

        border:
          "1px solid",

        borderColor:
          "divider",

        minHeight:
          270,

        display:
          "flex",

        flexDirection:
          "column",
      }}
    >

      <Box
        sx={{
          px:
            2.5,

          py:
            2.2,

          borderBottom:
            "1px solid",

          borderColor:
            "divider",
        }}
      >

        <Box
          sx={{
            display:
              "flex",

            alignItems:
              "flex-start",

            justifyContent:
              "space-between",

            gap:
              2,
          }}
        >

          <Box
            sx={{
              minWidth:
                0,
            }}
          >

            <Typography
              sx={{
                fontSize:
                  17,

                fontWeight:
                  600,
              }}
            >
              {offer.application
                .name}
            </Typography>


            <Typography
              sx={{
                mt:
                  0.35,

                fontSize:
                  11,

                color:
                  "text.secondary",

                fontFamily:
                  "monospace",
              }}
            >
              {offer.application
                .appKey}
            </Typography>

          </Box>


          <Chip
            size="small"

            label="Available"

            color="success"

            variant="outlined"

            sx={{
              height:
                23,

              fontSize:
                10,
            }}
          />

        </Box>


        <Typography
          sx={{
            mt:
              1.25,

            fontSize:
              12,

            color:
              "text.secondary",

            lineHeight:
              1.55,
          }}
        >
          {offer.application
            .description ||
            offer.description ||
            "No application description."}
        </Typography>

      </Box>


      <Box
        sx={{
          p:
            2.5,

          display:
            "grid",

          gridTemplateColumns:
            "1fr 1fr",

          gap:
            1.5,
        }}
      >

        <Meta
          label="Offer"
          value={
            offer.name
          }
        />


        <Meta
          label="Version"
          value={
            offer.version
              .version
          }
        />


        <Meta
          label="Build Type"
          value={
            formatStatus(
              offer.version
                .buildType
            )
          }
        />


        <Meta
          label="Deployment"
          value={
            formatStatus(
              offer.version
                .deploymentMode
            )
          }
        />


        <Meta
          label="Delivery"
          value={
            formatStatus(
              offer.deliveryType
            )
          }
        />


        <Meta
          label="Entitlement"
          value={
            entitlementSummary(
              offer
            )
          }
        />

      </Box>


      <Box
        sx={{
          mt:
            "auto",

          px:
            2.5,

          py:
            1.7,

          borderTop:
            "1px solid",

          borderColor:
            "divider",

          display:
            "flex",

          alignItems:
            "center",

          justifyContent:
            "space-between",

          gap:
            1.5,
        }}
      >

        <Typography
          sx={{
            fontSize:
              10.5,

            color:
              "text.secondary",
          }}
        >
          {offer.autoUpgrade
            ? "Automatic upgrades enabled"
            : "Manual version policy"}
        </Typography>


        <Button
          size="small"

          variant="contained"

          onClick={
            onSubscribe
          }
        >
          Subscribe
        </Button>

      </Box>

    </Box>
  );
}


function Meta({
  label,
  value,
}: {
  label:
    string;

  value:
    string;
}) {

  return (
    <Box>

      <Typography
        sx={{
          fontSize:
            9,

          color:
            "text.secondary",

          textTransform:
            "uppercase",

          letterSpacing:
            0.45,
        }}
      >
        {label}
      </Typography>


      <Typography
        sx={{
          mt:
            0.25,

          fontSize:
            11.5,

          fontWeight:
            600,
        }}
      >
        {value}
      </Typography>

    </Box>
  );
}
