"use client";

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
  Typography,
} from "@mui/material";

import OpenInNewOutlined
  from "@mui/icons-material/OpenInNewOutlined";


type StaticAppPreviewDialogProps = {
  open: boolean;

  applicationName: string;

  version: string;

  html: string;

  loading: boolean;

  error: string;

  onClose: () => void;
};


export default function StaticAppPreviewDialog({
  open,
  applicationName,
  version,
  html,
  loading,
  error,
  onClose,
}: StaticAppPreviewDialogProps) {

  return (
    <Dialog
      open={
        open
      }

      onClose={
        loading
          ? undefined
          : onClose
      }

      fullWidth

      maxWidth="xl"

      sx={{
        "& .MuiDialog-paper": {
          width:
            "96vw",

          maxWidth:
            "1500px",

          height:
            "88vh",

          maxHeight:
            "88vh",
        },
      }}
    >

      <DialogTitle
        sx={{
          pb: 1.25,
        }}
      >

        <Box
          sx={{
            display:
              "flex",

            flexDirection: {
              xs:
                "column",

              sm:
                "row",
            },

            alignItems: {
              xs:
                "flex-start",

              sm:
                "center",
            },

            justifyContent:
              "space-between",

            gap: 1,
          }}
        >

          <Box>

            <Typography
              sx={{
                fontSize:
                  18,

                fontWeight:
                  600,
              }}
            >
              Static Application Preview
            </Typography>


            <Typography
              sx={{
                mt: 0.35,

                fontSize:
                  12,

                color:
                  "text.secondary",
              }}
            >
              {applicationName}
              {" · "}
              Version
              {" "}
              {version}
            </Typography>

          </Box>


          <Box
            sx={{
              display:
                "flex",

              alignItems:
                "center",

              gap:
                0.75,
            }}
          >

            <OpenInNewOutlined
              sx={{
                fontSize:
                  16,

                color:
                  "text.secondary",
              }}
            />


            <Typography
              sx={{
                fontSize:
                  11,

                color:
                  "text.secondary",
              }}
            >
              Sandboxed preview
            </Typography>

          </Box>

        </Box>

      </DialogTitle>


      <Divider />


      <DialogContent
        sx={{
          p: 0,

          display:
            "flex",

          flexDirection:
            "column",

          minHeight:
            0,
        }}
      >

        {loading ? (

          <Box
            sx={{
              flex:
                1,

              display:
                "grid",

              placeItems:
                "center",

              minHeight:
                420,
            }}
          >

            <Box
              sx={{
                textAlign:
                  "center",
              }}
            >

              <CircularProgress
                size={30}
              />


              <Typography
                sx={{
                  mt:
                    1.5,

                  fontSize:
                    12,

                  color:
                    "text.secondary",
                }}
              >
                Loading static
                application...
              </Typography>

            </Box>

          </Box>

        ) : error ? (

          <Box
            sx={{
              p:
                3,
            }}
          >

            <Alert
              severity="error"
            >
              {error}
            </Alert>

          </Box>

        ) : html ? (

          <iframe
            title={`${applicationName} preview`}
            sandbox="allow-scripts"
            srcDoc={
              html
            }
            style={{
              width:
                "100%",

              flex:
                "1 1 auto",

              minHeight:
                "560px",

              border:
                0,

              background:
                "#ffffff",
            }}
          />

        ) : (

          <Box
            sx={{
              flex:
                1,

              display:
                "grid",

              placeItems:
                "center",

              minHeight:
                420,

              color:
                "text.secondary",

              fontSize:
                13,
            }}
          >
            No preview content
            available.
          </Box>

        )}

      </DialogContent>


      <Divider />


      <DialogActions
        sx={{
          px:
            2.5,

          py:
            1.5,

          display:
            "flex",

          alignItems:
            "center",

          gap:
            1,
        }}
      >

        <Typography
          sx={{
            mr:
              "auto",

            fontSize:
              10.5,

            color:
              "text.secondary",
          }}
        >
          Scripts may run inside
          the preview, but the
          application cannot access
          the AUGMIS parent page.
        </Typography>


        <Button
          onClick={
            onClose
          }

          disabled={
            loading
          }
        >
          Close
        </Button>

      </DialogActions>

    </Dialog>
  );
}
