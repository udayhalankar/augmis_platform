"use client";

import { createTheme } from "@mui/material/styles";

const theme = createTheme({
  palette: {
    mode: "light",

    primary: {
      main: "#1f5f8b",
    },

    background: {
      default: "#f4f6f8",
      paper: "#ffffff",
    },

    text: {
      primary: "#17212b",
      secondary: "#66727d",
    },

    divider: "#d9e0e5",
  },

  typography: {
    fontFamily:
      '"Segoe UI", Arial, Helvetica, sans-serif',

    h4: {
      fontWeight: 600,
      letterSpacing: "-0.02em",
    },

    h5: {
      fontWeight: 600,
    },

    h6: {
      fontWeight: 600,
    },

    button: {
      textTransform: "none",
      fontWeight: 600,
    },
  },

  shape: {
    borderRadius: 4,
  },

  components: {
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: "none",
        },
      },
    },

    MuiButton: {
      defaultProps: {
        disableElevation: true,
      },
    },

    MuiCard: {
      styleOverrides: {
        root: {
          boxShadow: "none",
          border: "1px solid #d9e0e5",
        },
      },
    },
  },
});

export default theme;