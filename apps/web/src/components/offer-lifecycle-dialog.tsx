"use client";

import {
  useState,
} from "react";

import axios from "axios";

import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  Typography,
} from "@mui/material";

import {
  activateApplicationOffer,
  ApplicationOffer,
  retireApplicationOffer,
} from "@/lib/publisher-center";


export type OfferLifecycleAction =
  | "activate"
  | "retire";


type Props = {
  open: boolean;

  action:
    OfferLifecycleAction | null;

  offer:
    ApplicationOffer | null;

  onClose: () => void;

  onCompleted:
    () => Promise<void>;
};


export default function OfferLifecycleDialog({
  open,
  action,
  offer,
  onClose,
  onCompleted,
}: Props) {

  const [
    processing,
    setProcessing,
  ] = useState(false);

  const [
    error,
    setError,
  ] = useState("");


  if (
    !offer ||
    !action
  ) {

    return null;
  }


  const activating =
    action === "activate";


  const handleConfirm =
    async () => {

      setProcessing(true);

      setError("");


      try {

        if (activating) {

          await activateApplicationOffer(
            offer.id
          );

        } else {

          await retireApplicationOffer(
            offer.id
          );
        }


        await onCompleted();

        onClose();

      } catch (actionError) {

        if (
          axios.isAxiosError(
            actionError
          )
        ) {

          const detail =
            actionError
              .response
              ?.data
              ?.detail;


          if (
            typeof detail ===
            "string"
          ) {

            setError(
              detail
            );

          } else {

            setError(
              activating
                ? "Offer could not be activated."
                : "Offer could not be retired."
            );
          }

        } else {

          setError(
            activating
              ? "Offer could not be activated."
              : "Offer could not be retired."
          );
        }

      } finally {

        setProcessing(false);
      }
    };


  return (
    <Dialog
      open={open}

      onClose={
        processing
          ? undefined
          : onClose
      }

      fullWidth
      maxWidth="xs"
    >

      <DialogTitle>

        {activating
          ? "Activate Commercial Offer"
          : "Retire Commercial Offer"}

      </DialogTitle>


      <DialogContent>

        <Stack
          spacing={2.5}
          sx={{
            pt: 1,
          }}
        >

          {error && (

            <Alert
              severity="error"
            >
              {error}
            </Alert>

          )}


          <Box>

            <Typography
              sx={{
                fontSize: 13,

                color:
                  "text.secondary",
              }}
            >
              Offer
            </Typography>


            <Typography
              sx={{
                mt: 0.4,

                fontSize: 16,

                fontWeight: 600,
              }}
            >
              {offer.name}
            </Typography>


            <Typography
              sx={{
                mt: 0.25,

                fontSize: 11,

                fontFamily:
                  "monospace",

                color:
                  "text.secondary",
              }}
            >
              {offer.offerKey}
            </Typography>

          </Box>


          {activating ? (

            <Alert
              severity="warning"
            >
              Activating this offer
              makes it available as an
              active commercial offer.
              Draft editing will no
              longer be allowed.
            </Alert>

          ) : (

            <Alert
              severity="warning"
            >
              Retiring this offer
              removes it from active
              commercial use. Existing
              subscriptions are not
              changed by this action.
            </Alert>

          )}

        </Stack>

      </DialogContent>


      <DialogActions
        sx={{
          px: 3,
          py: 2,
        }}
      >

        <Button
          onClick={
            onClose
          }

          disabled={
            processing
          }
        >
          Cancel
        </Button>


        <Button
          variant="contained"

          color={
            activating
              ? "primary"
              : "warning"
          }

          onClick={
            handleConfirm
          }

          disabled={
            processing
          }
        >

          {processing ? (

            <CircularProgress
              size={18}
              color="inherit"
            />

          ) : activating ? (

            "Activate Offer"

          ) : (

            "Retire Offer"

          )}

        </Button>

      </DialogActions>

    </Dialog>
  );
}