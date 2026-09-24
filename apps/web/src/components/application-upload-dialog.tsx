// application-upload-dialog.tsx
"use client";

import {
  ChangeEvent,
  MouseEvent,
  useEffect,
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
  Divider,
  Stack,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";

import UploadFileOutlined
  from "@mui/icons-material/UploadFileOutlined";

import CheckCircleOutlineOutlined
  from "@mui/icons-material/CheckCircleOutlineOutlined";

import {
  ApplicationUploadResult,
  uploadApplicationPackage,
  uploadStaticApplication,
} from "@/lib/publisher-center";


type ApplicationUploadDialogProps = {
  open: boolean;

  publisherId: string;

  publisherName: string;

  onClose: () => void;

  onUploaded: (
    result: ApplicationUploadResult
  ) => Promise<void> | void;
};


type UploadMode =
  "aaps" |
  "static";


function formatBytes(
  bytes: number
): string {

  if (bytes < 1024) {
    return `${bytes} B`;
  }

  if (
    bytes <
    1024 * 1024
  ) {

    return `${(
      bytes / 1024
    ).toFixed(1)} KB`;
  }

  return `${(
    bytes /
    1024 /
    1024
  ).toFixed(2)} MB`;
}


function slugify(
  value: string
): string {

  return String(
    value || ""
  )
    .toLowerCase()
    .trim()
    .replace(
      /[^a-z0-9]+/g,
      "-"
    )
    .replace(
      /^-+|-+$/g,
      ""
    )
    .slice(
      0,
      63
    );
}


function extractApiError(
  error: unknown
): string {

  if (
    !axios.isAxiosError(
      error
    )
  ) {

    return (
      "Application upload failed."
    );
  }


  const detail =
    error.response?.data
      ?.detail;


  if (
    Array.isArray(detail)
  ) {

    return detail
      .map((item) => {

        if (
          typeof item?.msg ===
          "string"
        ) {

          return item.msg;
        }

        return JSON.stringify(
          item
        );
      })
      .join(" — ");
  }


  if (
    typeof detail ===
    "string"
  ) {

    return detail;
  }


  if (
    detail &&
    typeof detail ===
    "object"
  ) {

    const message =
      detail.message;

    const errors =
      detail.errors;


    if (
      Array.isArray(
        errors
      ) &&
      errors.length > 0
    ) {

      return [
        message,
        ...errors,
      ]
        .filter(Boolean)
        .join(" — ");
    }


    if (
      typeof message ===
      "string"
    ) {

      return message;
    }
  }


  return (
    "Application upload failed."
  );
}


export default function ApplicationUploadDialog({
  open,
  publisherId,
  publisherName,
  onClose,
  onUploaded,
}: ApplicationUploadDialogProps) {

  const [
    mode,
    setMode,
  ] =
    useState<UploadMode>(
      "aaps"
    );


  const [
    file,
    setFile,
  ] =
    useState<File | null>(
      null
    );


  const [
    appName,
    setAppName,
  ] =
    useState("");


  const [
    appKey,
    setAppKey,
  ] =
    useState("");


  const [
    appKeyTouched,
    setAppKeyTouched,
  ] =
    useState(false);


  const [
    version,
    setVersion,
  ] =
    useState("1.0.0");


  const [
    description,
    setDescription,
  ] =
    useState("");


  const [
    uploading,
    setUploading,
  ] =
    useState(false);


  const [
    error,
    setError,
  ] =
    useState("");


  const [
    result,
    setResult,
  ] =
    useState<
      ApplicationUploadResult | null
    >(null);


  useEffect(
    () => {

      if (open) {

        setMode(
          "aaps"
        );

        setFile(
          null
        );

        setAppName(
          ""
        );

        setAppKey(
          ""
        );

        setAppKeyTouched(
          false
        );

        setVersion(
          "1.0.0"
        );

        setDescription(
          ""
        );

        setError(
          ""
        );

        setResult(
          null
        );
      }

    },
    [open]
  );


  const handleClose =
    () => {

      if (uploading) {
        return;
      }

      onClose();
    };


  const handleModeChange =
    (
      _event: MouseEvent<HTMLElement>,
      nextMode: UploadMode | null
    ) => {

      if (
        !nextMode ||
        uploading
      ) {
        return;
      }


      setMode(
        nextMode
      );

      setFile(
        null
      );

      setError(
        ""
      );

      setResult(
        null
      );
    };


  const handleAppNameChange =
    (
      value: string
    ) => {

      setAppName(
        value
      );


      if (
        !appKeyTouched
      ) {

        setAppKey(
          slugify(
            value
          )
        );
      }
    };


  const handleFileChange =
    (
      event:
        ChangeEvent<HTMLInputElement>
    ) => {

      const selected =
        event.target
          .files?.[0] ??
        null;


      setError(
        ""
      );

      setResult(
        null
      );


      if (!selected) {

        setFile(
          null
        );

        return;
      }


      const lowerName =
        selected.name
          .toLowerCase();


      if (
        mode === "aaps" &&
        !lowerName
          .endsWith(".zip")
      ) {

        setFile(
          null
        );

        setError(
          "AAPS / containerized applications require a ZIP package."
        );

        return;
      }


      if (
        mode === "static" &&
        !(
          lowerName
            .endsWith(".html") ||
          lowerName
            .endsWith(".htm")
        )
      ) {

        setFile(
          null
        );

        setError(
          "Static web applications currently require a single .html or .htm file."
        );

        return;
      }


      setFile(
        selected
      );
    };


  const validateStaticFields =
    (): string | null => {

      if (
        !appName.trim()
      ) {

        return (
          "Application name is required."
        );
      }


      if (
        !appKey.trim()
      ) {

        return (
          "Application key is required."
        );
      }


      if (
        !/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(
          appKey.trim()
        )
      ) {

        return (
          "Application key can contain only lowercase letters, numbers and hyphens."
        );
      }


      if (
        !/^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?$/.test(
          version.trim()
        )
      ) {

        return (
          "Version must use semantic version format, for example 1.0.0."
        );
      }


      return null;
    };


  const handleUpload =
    async () => {

      if (!file) {

        setError(
          mode === "static"
            ? "Select a standalone HTML application first."
            : "Select an application ZIP package first."
        );

        return;
      }


      if (
        mode === "static"
      ) {

        const validationError =
          validateStaticFields();


        if (
          validationError
        ) {

          setError(
            validationError
          );

          return;
        }
      }


      setUploading(
        true
      );

      setError(
        ""
      );

      setResult(
        null
      );


      try {

        const uploadResult =
          mode === "static"
            ? await uploadStaticApplication(
                publisherId,
                {
                  appName:
                    appName.trim(),

                  appKey:
                    appKey.trim(),

                  version:
                    version.trim(),

                  description:
                    description.trim(),

                  file,
                }
              )
            : await uploadApplicationPackage(
                publisherId,
                file
              );


        setResult(
          uploadResult
        );


        await onUploaded(
          uploadResult
        );

      } catch (
        uploadError
      ) {

        setError(
          extractApiError(
            uploadError
          )
        );

      } finally {

        setUploading(
          false
        );
      }
    };


  const canUpload =
    Boolean(
      file
    ) &&
    !uploading &&
    (
      mode === "aaps" ||
      (
        Boolean(
          appName.trim()
        ) &&
        Boolean(
          appKey.trim()
        ) &&
        Boolean(
          version.trim()
        )
      )
    );


  const fileInputId =
    mode === "static"
      ? "augmis-static-app-file"
      : "augmis-package-file";


  return (
    <Dialog
      open={
        open
      }
      onClose={
        handleClose
      }
      fullWidth
      maxWidth="sm"
    >

      <DialogTitle
        sx={{
          pb: 1,
        }}
      >
        Upload Application
      </DialogTitle>


      <DialogContent>

        <Typography
          sx={{
            fontSize:
              13,

            color:
              "text.secondary",

            mb: 2.5,
          }}
        >
          Add an application to
          {" "}
          <strong>
            {publisherName}
          </strong>.
        </Typography>


        {!result && (

          <Stack
            spacing={2.25}
          >

            <Box>

              <Typography
                sx={{
                  fontSize:
                    11,

                  fontWeight:
                    700,

                  color:
                    "text.secondary",

                  textTransform:
                    "uppercase",

                  letterSpacing:
                    0.5,

                  mb: 1,
                }}
              >
                Application Type
              </Typography>


              <ToggleButtonGroup
                exclusive
                fullWidth
                value={
                  mode
                }
                onChange={
                  handleModeChange
                }
                disabled={
                  uploading
                }
                size="small"
              >

                <ToggleButton
                  value="aaps"
                  sx={{
                    textTransform:
                      "none",

                    fontWeight:
                      600,
                  }}
                >
                  AAPS / Containerized
                </ToggleButton>


                <ToggleButton
                  value="static"
                  sx={{
                    textTransform:
                      "none",

                    fontWeight:
                      600,
                  }}
                >
                  Static Web Application
                </ToggleButton>

              </ToggleButtonGroup>

            </Box>


            {mode === "static" && (

              <Stack
                spacing={1.5}
              >

                <TextField
                  label=
                    "Application Name"
                  value={
                    appName
                  }
                  onChange={(
                    event
                  ) =>
                    handleAppNameChange(
                      event.target.value
                    )
                  }
                  required
                  fullWidth
                  size="small"
                  disabled={
                    uploading
                  }
                />


                <TextField
                  label=
                    "Application Key"
                  value={
                    appKey
                  }
                  onChange={(
                    event
                  ) => {

                    setAppKeyTouched(
                      true
                    );

                    setAppKey(
                      slugify(
                        event.target.value
                      )
                    );
                  }}
                  required
                  fullWidth
                  size="small"
                  disabled={
                    uploading
                  }
                  helperText=
                    "Lowercase letters, numbers and hyphens only."
                />


                <TextField
                  label=
                    "Version"
                  value={
                    version
                  }
                  onChange={(
                    event
                  ) =>
                    setVersion(
                      event.target.value
                    )
                  }
                  required
                  fullWidth
                  size="small"
                  disabled={
                    uploading
                  }
                  helperText=
                    "Semantic version, for example 1.0.0."
                />


                <TextField
                  label=
                    "Description"
                  value={
                    description
                  }
                  onChange={(
                    event
                  ) =>
                    setDescription(
                      event.target.value
                    )
                  }
                  fullWidth
                  multiline
                  minRows={2}
                  size="small"
                  disabled={
                    uploading
                  }
                />

              </Stack>

            )}


            <Box
              sx={{
                border:
                  "1px dashed",

                borderColor:
                  "divider",

                bgcolor:
                  "#f8fafb",

                p: 3,

                textAlign:
                  "center",
              }}
            >

              <UploadFileOutlined
                sx={{
                  fontSize:
                    38,

                  color:
                    "text.secondary",
                }}
              />


              <Typography
                sx={{
                  mt: 1,

                  fontSize:
                    14,

                  fontWeight:
                    600,
                }}
              >
                {mode === "static"
                  ? "Static Web Application"
                  : "AAPS Application Package"}
              </Typography>


              <Typography
                sx={{
                  mt: 0.5,

                  fontSize:
                    12,

                  color:
                    "text.secondary",
                }}
              >
                {mode === "static"
                  ? (
                      <>
                        Select one standalone
                        {" "}
                        <strong>
                          .html
                        </strong>
                        {" "}
                        or
                        {" "}
                        <strong>
                          .htm
                        </strong>
                        {" "}
                        file. Static web apps
                        are validated but do
                        not require a Docker
                        image build.
                      </>
                    )
                  : (
                      <>
                        Select a
                        {" "}
                        <strong>
                          .zip
                        </strong>
                        {" "}
                        package. The control
                        plane will validate
                        its manifest,
                        structure and
                        version.
                      </>
                    )}
              </Typography>


              <input
                key={
                  mode
                }
                id={
                  fileInputId
                }
                type="file"
                accept={
                  mode === "static"
                    ? ".html,.htm,text/html"
                    : ".zip,application/zip"
                }
                hidden
                onChange={
                  handleFileChange
                }
              />


              <Box
                sx={{
                  mt: 2,
                }}
              >

                <label
                  htmlFor={
                    fileInputId
                  }
                >

                  <Button
                    component="span"
                    variant="outlined"
                    disabled={
                      uploading
                    }
                  >
                    {mode === "static"
                      ? "Choose HTML"
                      : "Choose ZIP"}
                  </Button>

                </label>

              </Box>

            </Box>


            {file && (

              <Box
                sx={{
                  border:
                    "1px solid",

                  borderColor:
                    "divider",

                  bgcolor:
                    "#ffffff",

                  px: 2,
                  py: 1.5,
                }}
              >

                <Typography
                  sx={{
                    fontSize:
                      13,

                    fontWeight:
                      600,

                    wordBreak:
                      "break-all",
                  }}
                >
                  {file.name}
                </Typography>


                <Typography
                  sx={{
                    mt: 0.25,

                    fontSize:
                      11,

                    color:
                      "text.secondary",
                  }}
                >
                  {formatBytes(
                    file.size
                  )}
                </Typography>

              </Box>

            )}


            {error && (

              <Alert
                severity="error"
              >
                {error}
              </Alert>

            )}

          </Stack>

        )}


        {result && (

          <Stack
            spacing={2.5}
          >

            <Alert
              severity="success"
              icon={
                <CheckCircleOutlineOutlined />
              }
            >
              {result.version
                .buildType ===
                "static_web"
                ? (
                    "Static web application successfully validated and registered."
                  )
                : (
                    "Application package successfully validated and registered."
                  )}
            </Alert>


            <Box
              sx={{
                border:
                  "1px solid",

                borderColor:
                  "divider",
              }}
            >

              <ResultRow
                label=
                  "Application"
                value={
                  result.application
                    .name
                }
              />


              <ResultRow
                label=
                  "App Key"
                value={
                  result.application
                    .appKey
                }
              />


              <ResultRow
                label=
                  "Version"
                value={
                  result.version
                    .version
                }
              />


              <ResultRow
                label=
                  "Build Type"
                value={
                  result.version
                    .buildType
                }
              />


              <ResultRow
                label=
                  "Deployment Mode"
                value={
                  result.version
                    .deploymentMode
                }
              />


              <ResultRow
                label=
                  "Package Status"
                value={
                  result.package
                    .status
                }
              />


              <ResultRow
                label=
                  "Package Size"
                value={
                  formatBytes(
                    result.package
                      .sizeBytes
                  )
                }
              />


              <ResultRow
                label=
                  "SHA-256"
                value={
                  result.package
                    .sha256
                }
                mono
                last
              />

            </Box>


            <Typography
              sx={{
                fontSize:
                  12,

                color:
                  "text.secondary",
              }}
            >
              {result.version
                .buildType ===
                "static_web"
                ? (
                    "This static application is ready for preview. A Docker runtime image is not required."
                  )
                : (
                    "The application version is validated but has not yet been built into a runtime image."
                  )}
            </Typography>

          </Stack>

        )}

      </DialogContent>


      <Divider />


      <DialogActions
        sx={{
          px: 3,
          py: 2,
        }}
      >

        {!result ? (

          <>

            <Button
              onClick={
                handleClose
              }
              disabled={
                uploading
              }
            >
              Cancel
            </Button>


            <Button
              variant="contained"

              disabled={
                !canUpload
              }

              onClick={
                handleUpload
              }

              startIcon={
                uploading
                  ? (
                      <CircularProgress
                        size={16}
                        color="inherit"
                      />
                    )
                  : (
                      <UploadFileOutlined />
                    )
              }
            >
              {uploading
                ? "Validating..."
                : "Upload & Validate"}
            </Button>

          </>

        ) : (

          <Button
            variant="contained"
            onClick={
              handleClose
            }
          >
            Done
          </Button>

        )}

      </DialogActions>

    </Dialog>
  );
}


function ResultRow({
  label,
  value,
  mono = false,
  last = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
  last?: boolean;
}) {

  return (
    <Box
      sx={{
        display:
          "grid",

        gridTemplateColumns:
          "150px minmax(0, 1fr)",

        px: 2,
        py: 1.25,

        borderBottom:
          last
            ? "none"
            : "1px solid",

        borderColor:
          "divider",

        gap: 2,
      }}
    >

      <Typography
        sx={{
          fontSize:
            11,

          color:
            "text.secondary",

          textTransform:
            "uppercase",

          letterSpacing:
            0.4,
        }}
      >
        {label}
      </Typography>


      <Typography
        sx={{
          fontSize:
            12,

          fontWeight:
            600,

          fontFamily:
            mono
              ? "monospace"
              : "inherit",

          wordBreak:
            "break-all",
        }}
      >
        {value}
      </Typography>

    </Box>
  );
}
