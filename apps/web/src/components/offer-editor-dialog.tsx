"use client";

import {
  useEffect,
  useState,
} from "react";

import axios from "axios";

import {
  Alert,
  Box,
  Button,
  Checkbox,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";

import {
  ApplicationOffer,
  ApplicationVersion,
  createApplicationOffer,
  updateApplicationOffer,
} from "@/lib/publisher-center";


type Props = {
  open: boolean;

  applicationId: string;

  versions:
    ApplicationVersion[];

  offer:
    ApplicationOffer | null;

  onClose: () => void;

  onSaved:
    () => Promise<void>;
};


export default function OfferEditorDialog({
  open,
  applicationId,
  versions,
  offer,
  onClose,
  onSaved,
}: Props) {

  const editing =
    Boolean(offer);


  const [
    offerKey,
    setOfferKey,
  ] = useState("");


  const [
    name,
    setName,
  ] = useState("");


  const [
    description,
    setDescription,
  ] = useState("");


  const [
    versionPolicy,
    setVersionPolicy,
  ] = useState(
    "same_major"
  );


  const [
    pinnedVersionId,
    setPinnedVersionId,
  ] = useState("");


  const [
    autoUpgrade,
    setAutoUpgrade,
  ] = useState(false);


  const [
    maxInstances,
    setMaxInstances,
  ] = useState("1");


  const [
    saving,
    setSaving,
  ] = useState(false);


  const [
    error,
    setError,
  ] = useState("");


  const imageReadyVersions =
    versions.filter(
      (version) =>
        version.status ===
        "image_ready"
    );


  useEffect(
    () => {

      if (!open) {
        return;
      }


      setError("");


      if (offer) {

        setOfferKey(
          offer.offerKey ??
          ""
        );

        setName(
          offer.name ??
          ""
        );

        setDescription(
          offer.description ??
          ""
        );

        setVersionPolicy(
          offer.versionPolicy ??
          "same_major"
        );

        setPinnedVersionId(
          offer.pinnedVersionId ??
          ""
        );

        setAutoUpgrade(
          offer.autoUpgrade ??
          false
        );


        const deploy =
          (
            offer.entitlements ??
            []
          ).find(
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


        setMaxInstances(
          String(
            value?.maxInstances ??
            1
          )
        );

        console.log(
          "EDIT OFFER OBJECT:",
          offer
        );

        console.log(
          "EDIT ENTITLEMENTS:",
          offer.entitlements
        );

      } else {

        setOfferKey("");

        setName("");

        setDescription("");

        setVersionPolicy(
          "same_major"
        );

        setPinnedVersionId("");

        setAutoUpgrade(false);

        setMaxInstances("1");
      }

    },
    [
      open,
      offer,
    ]
  );


  const handleSave =
    async () => {

      setError("");


      const parsedMax =
        Number(
          maxInstances
        );


      if (
        !Number.isInteger(
          parsedMax
        ) ||
        parsedMax < 1
      ) {

        setError(
          "Maximum instances must be a positive whole number."
        );

        return;
      }


      if (
        versionPolicy ===
          "pinned" &&
        !pinnedVersionId
      ) {

        setError(
          "Select an image-ready version for the pinned policy."
        );

        return;
      }


      setSaving(true);


      const payload = {
        name:
          name.trim(),

        description:
          description.trim()
            ? description.trim()
            : null,

        version_policy:
          versionPolicy,

        pinned_version_id:
          versionPolicy ===
            "pinned"
            ? pinnedVersionId
            : null,

        auto_upgrade:
          autoUpgrade,

        entitlements: [
          {
            code:
              "application.deploy",

            value: {
              maxInstances:
                parsedMax,
            },
          },
        ],
      };


      try {

        if (
          editing &&
          offer
        ) {

          await updateApplicationOffer(
            offer.id,
            payload
          );

        } else {

          await createApplicationOffer(
            applicationId,
            {
              ...payload,

              offer_key:
                offerKey.trim(),

              delivery_type:
                "hosted_dedicated",
            }
          );
        }


        await onSaved();

        onClose();

      } catch (saveError) {

        if (
          axios.isAxiosError(
            saveError
          )
        ) {

          const detail =
            saveError
              .response
              ?.data
              ?.detail;


          if (
            typeof detail ===
            "string"
          ) {

            setError(detail);

          } else {

            setError(
              "Offer could not be saved."
            );
          }

        } else {

          setError(
            "Offer could not be saved."
          );
        }

      } finally {

        setSaving(false);
      }
    };


  return (
    <Dialog
      open={open}

      onClose={
        saving
          ? undefined
          : onClose
      }

      maxWidth="sm"
      fullWidth
    >

      <DialogTitle>
        {editing
          ? "Edit Draft Offer"
          : "Create Commercial Offer"}
      </DialogTitle>


      <DialogContent>

        <Stack
          spacing={2.4}
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


          <TextField
            label="Offer Key"

            value={
              offerKey
            }

            onChange={
              (event) =>
                setOfferKey(
                  event.target.value
                    .toLowerCase()
                    .replace(
                      /[^a-z0-9-]/g,
                      "-"
                    )
                )
            }

            disabled={
              editing
            }

            helperText={
              editing
                ? "Offer key is immutable."
                : "Example: hosted-professional"
            }

            required
            fullWidth
          />


          <TextField
            label="Offer Name"

            value={
              name
            }

            onChange={
              (event) =>
                setName(
                  event.target.value
                )
            }

            required
            fullWidth
          />


          <TextField
            label="Description"

            value={
              description
            }

            onChange={
              (event) =>
                setDescription(
                  event.target.value
                )
            }

            multiline
            minRows={3}
            fullWidth
          />


          <TextField
            label="Delivery Type"

            value=
              "Hosted Dedicated"

            disabled

            fullWidth
          />


          <TextField
            select

            label="Version Policy"

            value={
              versionPolicy
            }

            onChange={
              (event) => {

                setVersionPolicy(
                  event.target.value
                );

                if (
                  event.target.value
                  !== "pinned"
                ) {

                  setPinnedVersionId(
                    ""
                  );
                }
              }
            }

            fullWidth
          >

            <MenuItem
              value="same_major"
            >
              Same Major
            </MenuItem>

            <MenuItem
              value="any"
            >
              Any Image-Ready Version
            </MenuItem>

            <MenuItem
              value="pinned"
            >
              Pinned Version
            </MenuItem>

          </TextField>


          {versionPolicy ===
            "pinned" && (

            <TextField
              select

              label=
                "Pinned Version"

              value={
                pinnedVersionId
              }

              onChange={
                (event) =>
                  setPinnedVersionId(
                    event.target.value
                  )
              }

              required
              fullWidth
            >

              {imageReadyVersions.map(
                (version) => (

                  <MenuItem
                    key={
                      version.id
                    }
                    value={
                      version.id
                    }
                  >
                    {version.version}
                  </MenuItem>

                )
              )}

            </TextField>

          )}


          <TextField
            label=
              "Maximum Instances"

            type="number"

            value={
              maxInstances
            }

            onChange={
              (event) =>
                setMaxInstances(
                  event.target.value
                )
            }

            slotProps={{
              htmlInput: {
                min: 1,
                step: 1,
              },
            }}

            helperText=
              "Entitlement: application.deploy"

            fullWidth
          />


          <FormControlLabel
            control={
              <Checkbox
                checked={
                  autoUpgrade
                }

                onChange={
                  (event) =>
                    setAutoUpgrade(
                      event.target.checked
                    )
                }
              />
            }

            label={
              <Box>

                <Typography
                  sx={{
                    fontSize: 13,
                    fontWeight: 600,
                  }}
                >
                  Automatic upgrades
                </Typography>

                <Typography
                  sx={{
                    fontSize: 11,
                    color:
                      "text.secondary",
                  }}
                >
                  Permit automatic
                  upgrades within the
                  configured version
                  policy.
                </Typography>

              </Box>
            }
          />

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
            saving
          }
        >
          Cancel
        </Button>


        <Button
          variant="contained"

          onClick={
            handleSave
          }

          disabled={
            saving ||
            !name.trim() ||
            (
              !editing &&
              !offerKey.trim()
            )
          }
        >

          {saving ? (

            <CircularProgress
              size={18}
              color="inherit"
            />

          ) : editing ? (

            "Save Changes"

          ) : (

            "Create Draft"

          )}

        </Button>

      </DialogActions>

    </Dialog>
  );
}