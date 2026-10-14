"use client";

import { useMemo, useRef, useState } from "react";
import AddOutlinedIcon from "@mui/icons-material/AddOutlined";
import DeleteOutlineOutlinedIcon from "@mui/icons-material/DeleteOutlineOutlined";
import RestartAltOutlinedIcon from "@mui/icons-material/RestartAltOutlined";
import {
  Alert, Autocomplete, Box, Button, Checkbox, Chip, Dialog, DialogActions, DialogContent,
  DialogTitle, Divider, IconButton, MenuItem, TextField, Tooltip, Typography,
} from "@mui/material";
import { RUNTIME_CONFIG_PROFILES, RUNTIME_VARIABLE_CATALOG,
  type RuntimeVariableTemplate } from "@/lib/runtime-variable-catalog";

type VariableRow = { id: number; name: string; value: string };
type Props = {
  initialVariables: Record<string, string>;
  revision: number | null;
  busy: boolean;
  onSave: (variables: Record<string, string>) => Promise<void>;
};
type Errors = { names: Record<number, string>; values: Record<number, string>; general: string | null };

const VALID_NAME = /^[A-Z][A-Z0-9_]{0,63}$/;
const RESERVED = ["AUGMIS_", "DOCKER_", "LD_", "PYTHONPATH"];
const MAX_VARIABLES = 64;
const MAX_VALUE_BYTES = 2048;
const MAX_TOTAL_BYTES = 16384;
const SECRET_NAME = /(?:PASSWORD|SECRET|TOKEN|API_KEY|PRIVATE_KEY|CREDENTIAL)/;
const encoder = new TextEncoder();

function validate(rows: VariableRow[]): Errors {
  const names: Record<number, string> = {};
  const values: Record<number, string> = {};
  const seen = new Set<string>();
  let total = 0;
  for (const row of rows) {
    const name = row.name.trim();
    if (!name) names[row.id] = "Select or enter a variable name.";
    else if (!VALID_NAME.test(name)) names[row.id] = "Uppercase letters, digits and _, starting with a letter (max 64).";
    else if (RESERVED.some((prefix) => name.startsWith(prefix))) names[row.id] = "Reserved by AUGMIS/runtime.";
    else if (SECRET_NAME.test(name)) names[row.id] = "Sensitive keys are not supported here. Use a secrets provider later.";
    else if (seen.has(name)) names[row.id] = "Already present; choose another variable.";
    seen.add(name);
    if (encoder.encode(row.value).length > MAX_VALUE_BYTES) values[row.id] = "Value exceeds 2 KiB.";
    if (row.value.includes("\0")) values[row.id] = "Null characters are not allowed.";
    total += encoder.encode(name).length + encoder.encode(row.value).length;
  }
  return {
    names, values,
    general: rows.length > MAX_VARIABLES ? "At most 64 variables are allowed."
      : total > MAX_TOTAL_BYTES ? "The total configuration exceeds 16 KiB." : null,
  };
}

const rowList = (variables: Record<string, string>): VariableRow[] =>
  Object.entries(variables).sort(([a], [b]) => a.localeCompare(b))
    .map(([name, value], id) => ({ id: id + 1, name, value }));

/** Catalog plus custom variables. All authorisation, concurrency and persistence stay server-side. */
export default function RuntimeEnvironmentVariablesEditor({ initialVariables, revision, busy, onSave }: Props) {
  const original = useMemo(() => rowList(initialVariables), [initialVariables]);
  const nextId = useRef(original.length);
  const [rows, setRows] = useState<VariableRow[]>(() => original);
  const [chosen, setChosen] = useState<RuntimeVariableTemplate | null>(null);
  const [openCatalog, setOpenCatalog] = useState(false);
  const [selectedNames, setSelectedNames] = useState<string[]>([]);
  const [filter, setFilter] = useState("");
  const [showProfiles, setShowProfiles] = useState(false);
  const [notice, setNotice] = useState("");
  const used = useMemo(() => new Set(rows.map((r) => r.name.trim())), [rows]);
  const options = useMemo(() => RUNTIME_VARIABLE_CATALOG.filter((v) => !used.has(v.name)), [used]);
  const catalogFiltered = useMemo(() => RUNTIME_VARIABLE_CATALOG.filter((t) =>
    !used.has(t.name) && `${t.name} ${t.category} ${t.description}`.toLowerCase().includes(filter.toLowerCase())), [used, filter]);
  const errors = useMemo(() => validate(rows), [rows]);
  const invalid = !!errors.general || Object.keys(errors.names).length > 0 || Object.keys(errors.values).length > 0;
  const normalize = (list: VariableRow[]) => Object.fromEntries(list.map((r) => [r.name.trim(), r.value]));
  const dirty = JSON.stringify(normalize(rows)) !== JSON.stringify(normalize(original));
  const update = (id: number, key: "name" | "value", value: string) => {
    setRows((r) => r.map((item) => item.id === id ? { ...item, [key]: value } : item));
    setNotice("");
  };
  const addNames = (names: readonly string[]) => {
    let added = 0;
    const existing = new Set(rows.map((r) => r.name.trim()));
    const next = [...rows];
    for (const name of names) {
      const template = RUNTIME_VARIABLE_CATALOG.find((item) => item.name === name);
      if (!template || existing.has(name) || next.length >= MAX_VARIABLES) continue;
      nextId.current += 1;
      next.push({ id: nextId.current, name, value: template.defaultValue });
      existing.add(name); added += 1;
    }
    setRows(next);
    setNotice(added ? `${added} suggestion${added === 1 ? "" : "s"} added. Review values before saving.` : "Nothing new to add.");
  };
  const addCustom = () => {
    if (rows.length >= MAX_VARIABLES || busy) return;
    nextId.current += 1;
    setRows((current) => [...current, { id: nextId.current, name: "", value: "" }]);
    setNotice("");
  };
  const reset = () => { setRows(rowList(initialVariables)); nextId.current = original.length; setNotice("Edits discarded."); };
  const doSave = () => { if (!busy && dirty && !invalid) void onSave(normalize(rows)); };

  return <Box>
    <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 2, flexWrap: "wrap", mb: 1 }}>
      <Box>
        <Typography sx={{ fontWeight: 600 }}>Environment configuration</Typography>
        <Typography variant="caption" color="text.secondary">{rows.length} / {MAX_VARIABLES} configured · Revision {revision ?? "new"}</Typography>
      </Box>
      <Box sx={{ display: "flex", gap: 1, flexWrap: "wrap" }}>
        <Button size="small" variant="outlined" onClick={() => setShowProfiles((open) => !open)} disabled={busy}>Suggested sets</Button>
        <Button size="small" variant="outlined" onClick={() => setOpenCatalog(true)} disabled={busy}>Browse full catalog</Button>
        <Button size="small" startIcon={<AddOutlinedIcon />} onClick={addCustom} disabled={busy || rows.length >= MAX_VARIABLES}>Custom variable</Button>
      </Box>
    </Box>
    <Alert severity="info" sx={{ mb: 2 }}>
      These are <strong>suggested environment names</strong>, not universal Docker/AUGMIS settings.
      Your application must explicitly read a variable before it affects behavior. Use non-secret values only.
    </Alert>
    {showProfiles && <Box sx={{ p: 1.5, border: "1px solid", borderColor: "divider", mb: 2, bgcolor: "background.paper" }}>
      <Typography variant="subtitle2" sx={{ mb: 1 }}>Add a ready-made configuration set</Typography>
      <Box sx={{ display: "flex", gap: 1, flexWrap: "wrap" }}>
        {RUNTIME_CONFIG_PROFILES.map((profile) => <Tooltip key={profile.id} title={profile.description}>
          <span><Button variant="outlined" size="small" disabled={busy || rows.length >= MAX_VARIABLES}
            onClick={() => addNames(profile.names)}>{profile.title}</Button></span>
        </Tooltip>)}
      </Box>
    </Box>}
    <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "minmax(0, 1fr) auto auto" }, gap: 1, mb: 2, alignItems: "start" }}>
      <Autocomplete
        options={options} value={chosen} onChange={(_, value) => setChosen(value)}
        groupBy={(item) => item.category}
        getOptionLabel={(item) => item.name}
        isOptionEqualToValue={(a, b) => a.name === b.name}
        renderOption={(props, option) => <li {...props} key={option.name}>
          <Box><Typography sx={{ fontSize: 13, fontWeight: 600 }}>{option.name}</Typography>
          <Typography variant="caption" color="text.secondary">{option.description}</Typography></Box>
        </li>}
        renderInput={(params) => <TextField {...params} size="small" label="Find a variable by name or category"
          helperText={chosen?.description ?? "Select a suggestion or use Custom variable"} />}
        disabled={busy || rows.length >= MAX_VARIABLES}
      />
      <Button size="small" variant="contained" sx={{ mt: 0.25, minHeight: 37 }} disabled={!chosen || busy}
        onClick={() => { if (chosen) addNames([chosen.name]); setChosen(null); }}>Add selected</Button>
      <Chip size="small" variant="outlined" sx={{ mt: 1 }} label={`${options.length} suggestions available`} />
    </Box>

    <Box sx={{ border: "1px solid", borderColor: "divider", mb: 1.5 }}>
      <Box sx={{ display: { xs: "none", md: "grid" }, gridTemplateColumns: "minmax(200px,1fr) minmax(200px,1.75fr) 42px", px: 2, py: 1, gap: 1.5, bgcolor: "#f6f8fa" }}>
        <Typography variant="caption" sx={{ fontWeight: 700 }}>VARIABLE NAME</Typography>
        <Typography variant="caption" sx={{ fontWeight: 700 }}>VALUE</Typography>
        <Box />
      </Box>
      <Divider />
      {rows.length === 0 && <Box sx={{ p: 3, textAlign: "center" }}><Typography color="text.secondary">No variables configured. Select one above or browse the catalog.</Typography></Box>}
      {rows.map((row, index) => {
        const template = RUNTIME_VARIABLE_CATALOG.find((v) => v.name === row.name);
        return <Box key={row.id} sx={{ display: "grid", gridTemplateColumns: { xs: "minmax(0,1fr) 40px", md: "minmax(200px,1fr) minmax(200px,1.75fr) 42px" }, gap: 1.5, px: 2, py: 1.25, borderTop: index ? "1px solid" : "none", borderColor: "divider", alignItems: "start" }}>
          <TextField label="Name" size="small" value={row.name} disabled={busy} onChange={(e) => update(row.id, "name", e.target.value)}
            helperText={errors.names[row.id] ?? template?.description ?? "App-defined environment name"} error={!!errors.names[row.id]}
            sx={{ "& input": { fontFamily: "monospace" } }} slotProps={{ htmlInput: { maxLength: 64, autoComplete: "off", spellCheck: false } }} />
          <Box sx={{ gridColumn: { xs: "1", md: "2" }, gridRow: { xs: "2", md: "auto" } }}>
            <TextField fullWidth label="Value" size="small" value={row.value} disabled={busy} onChange={(e) => update(row.id, "value", e.target.value)}
              error={!!errors.values[row.id]} helperText={errors.values[row.id] ?? " "}
              sx={{ "& input": { fontFamily: "monospace" } }} slotProps={{ htmlInput: { autoComplete: "off", spellCheck: false } }} />
            {template?.values && <Box sx={{ display: "flex", gap: 0.5, flexWrap: "wrap", mt: 0.25 }}>
              {template.values.map((v) => <Button key={v} size="small" variant={row.value === v ? "contained" : "text"}
                disabled={busy} onClick={() => update(row.id, "value", v)} sx={{ minWidth: "auto", py: 0, fontSize: 11 }}>{v}</Button>)}
            </Box>}
          </Box>
          <Tooltip title={`Remove ${row.name || "variable"}`}><span><IconButton size="small" color="error" aria-label={`Remove ${row.name || "variable"}`}
            disabled={busy} onClick={() => { setRows((old) => old.filter((item) => item.id !== row.id)); setNotice(""); }}>
            <DeleteOutlineOutlinedIcon fontSize="small" />
          </IconButton></span></Tooltip>
        </Box>;
      })}
    </Box>
    {notice && <Alert severity="info" sx={{ mb: 1 }}>{notice}</Alert>}
    {errors.general && <Alert severity="error" sx={{ mb: 1 }}>{errors.general}</Alert>}
    {dirty && !invalid && <Alert severity="warning" sx={{ mb: 1 }}>Unsaved changes. Saving does not restart an existing container.</Alert>}
    <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 1, flexWrap: "wrap" }}>
      <Typography variant="caption" color="text.secondary">Saving uses the existing revision check; changes apply on the next container start.</Typography>
      <Box sx={{ display: "flex", gap: 1 }}>
        <Button size="small" variant="outlined" startIcon={<RestartAltOutlinedIcon />} disabled={!dirty || busy} onClick={reset}>Discard edits</Button>
        <Button size="small" variant="contained" disabled={busy || !dirty || invalid} onClick={doSave}>Save configuration</Button>
      </Box>
    </Box>

    <Dialog open={openCatalog} onClose={() => setOpenCatalog(false)} fullWidth maxWidth="md">
      <DialogTitle>Environment variable catalog</DialogTitle>
      <DialogContent dividers sx={{ maxHeight: "65vh" }}>
        <Alert severity="info" sx={{ mb: 2 }}>Select multiple suggested keys. Defaults are editable after adding. These are not automatically supported by every application.</Alert>
        <TextField fullWidth size="small" label="Search name, category or description" value={filter}
          onChange={(e) => setFilter(e.target.value)} sx={{ mb: 1.5 }} />
        <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", mb: 1 }}>
          <Typography variant="caption">{catalogFiltered.length} available / {RUNTIME_VARIABLE_CATALOG.length} suggestions</Typography>
          <Button size="small" disabled={!catalogFiltered.length} onClick={() => setSelectedNames(catalogFiltered.map((v) => v.name))}>Select filtered</Button>
        </Box>
        {catalogFiltered.map((item) => <Box key={item.name} sx={{ borderBottom: "1px solid", borderColor: "divider", display: "flex", alignItems: "center", py: 0.5 }}>
          <Checkbox size="small" disabled={busy} checked={selectedNames.includes(item.name)}
            onChange={(_, checked) => setSelectedNames((current) => checked ? [...current, item.name] : current.filter((name) => name !== item.name))} />
          <Box><Typography sx={{ fontSize: 13, fontWeight: 600 }}>{item.name} <Typography component="span" variant="caption" color="text.secondary">— {item.category}</Typography></Typography>
          <Typography variant="caption" color="text.secondary">{item.description} · suggested: {item.defaultValue || "(blank)"}</Typography></Box>
        </Box>)}
        {!catalogFiltered.length && <Typography color="text.secondary" sx={{ py: 2 }}>No available suggestions match the search.</Typography>}
      </DialogContent>
      <DialogActions>
        <Button onClick={() => { setOpenCatalog(false); setSelectedNames([]); }}>Cancel</Button>
        <Button variant="contained" disabled={busy || selectedNames.length === 0}
          onClick={() => { addNames(selectedNames); setSelectedNames([]); setOpenCatalog(false); }}>Add {selectedNames.length} variable(s)</Button>
      </DialogActions>
    </Dialog>
  </Box>;
}
