"use client";

import type { ReactNode } from "react";
import { Box, Tab, Tabs } from "@mui/material";

export type AdministrationTab = { value: string; label: string };

/** Shared Administration tab strip: same typography, geometry and selected-state across sections. */
export default function AdministrationTabs({
  value,
  tabs,
  ariaLabel,
  onChange,
  action,
}: {
  value: string;
  tabs: readonly AdministrationTab[];
  ariaLabel: string;
  onChange?: (value: string) => void;
  action?: ReactNode;
}) {
  return (
    <Box
      sx={{
        bgcolor: "background.paper",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        flexWrap: "wrap",
        gap: 1,
        px: 2.5,
        borderBottom: "1px solid",
        borderColor: "divider",
        minWidth: 0,
      }}
    >
      <Tabs
        value={value}
        onChange={(_event, next: string) => onChange?.(next)}
        aria-label={ariaLabel}
        variant="scrollable"
        scrollButtons="auto"
        sx={{
          minHeight: 48,
          minWidth: 0,
          "& .MuiTabs-indicator": { height: 3 },
          "& .MuiTab-root": {
            minHeight: 48,
            px: 2.5,
            fontSize: 13,
            fontWeight: 600,
            textTransform: "none",
          },
        }}
      >
        {tabs.map((tab) => (
          <Tab key={tab.value} value={tab.value} label={tab.label} />
        ))}
      </Tabs>
      {action && <Box sx={{ display: "flex", alignItems: "center", py: 0.75 }}>{action}</Box>}
    </Box>
  );
}
