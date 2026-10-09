"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import axios from "axios";
import {
  Alert, Box, Button, Checkbox, Chip, CircularProgress, Dialog,
  DialogActions, DialogContent, DialogTitle, FormControl, InputLabel,
  ListItemText, MenuItem, Select, Stack, TextField, Typography,
} from "@mui/material";
import { useAuth } from "@/context/auth-context";
import {
  addPublisherMember,
  changePublisherMemberRoles,
  loadPublisherMembers,
  loadPublisherRoles,
  setPublisherMemberStatus,
  type PublisherMember,
  type PublisherRole,
} from "@/lib/publisher-users";

type Props = {
  open: boolean;
  publisherId: string;
  publisherName: string;
  onClose: () => void;
};

function errorText(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail: unknown = error.response?.data?.detail;
    if (typeof detail === "string") return detail;
  }
  return error instanceof Error ? error.message : "Publisher member request failed.";
}

export default function PublisherUsersDialog({
  open, publisherId, publisherName, onClose,
}: Props) {
  const { user } = useAuth();
  const [members, setMembers] = useState<PublisherMember[]>([]);
  const [roles, setRoles] = useState<PublisherRole[]>([]);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [email, setEmail] = useState("");
  const [addRoles, setAddRoles] = useState<string[]>(["publisher_developer"]);
  const [editingId, setEditingId] = useState("");
  const [editRoles, setEditRoles] = useState<string[]>([]);

  const refresh = useCallback(async () => {
    if (!publisherId) return;
    setLoading(true);
    setError("");
    try {
      const [memberRows, roleRows] = await Promise.all([
        loadPublisherMembers(publisherId), loadPublisherRoles(publisherId),
      ]);
      setMembers(memberRows);
      setRoles(roleRows);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setLoading(false);
    }
  }, [publisherId]);

  useEffect(() => {
    if (open) {
      setEditingId("");
      setSuccess("");
      setEmail("");
      setAddRoles(["publisher_developer"]);
      void refresh();
    }
  }, [open, refresh]);

  const actorMembership = useMemo(
    () => members.find((member) =>
      member.user.id === user?.id && member.status === "active"),
    [members, user?.id],
  );
  const isPublisherOwner = Boolean(
    actorMembership?.roles.some((role) => role.code === "publisher_owner")
  );
  const activeRoleOptions = roles.filter(
    (role) => isPublisherOwner || role.code !== "publisher_owner"
  );

  const run = async (id: string, operation: () => Promise<unknown>, message: string): Promise<boolean> => {
    setBusyId(id);
    setError("");
    setSuccess("");
    try {
      await operation();
      setEditingId("");
      setSuccess(message);
      await refresh();
      return true;
    } catch (e) {
      setError(errorText(e));
      return false;
    } finally {
      setBusyId("");
    }
  };

  const handleAdd = async () => {
    if (!email.trim() || !addRoles.length) return;
    const added = await run("new", () => addPublisherMember(publisherId, email.trim(), addRoles),
      "Publisher user added successfully.");
    if (added) setEmail("");
  };

  const roleSelect = (
    value: string[], onChange: (roles: string[]) => void, label: string,
  ) => (
    <FormControl size="small" fullWidth>
      <InputLabel>{label}</InputLabel>
      <Select<string[]>
        multiple
        value={value}
        label={label}
        onChange={(event) => onChange(
          typeof event.target.value === "string"
            ? event.target.value.split(",") : event.target.value
        )}
        renderValue={(selected) =>
          selected.map((code) => roles.find((role) => role.code === code)?.name ?? code).join(", ")
        }
      >
        {activeRoleOptions.map((role) => (
          <MenuItem key={role.id} value={role.code}>
            <Checkbox size="small" checked={value.includes(role.code)} />
            <ListItemText primary={role.name} />
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  );

  return (
    <Dialog open={open} onClose={busyId ? undefined : onClose} maxWidth="lg" fullWidth>
      <DialogTitle sx={{ borderBottom: "1px solid", borderColor: "divider" }}>
        <Typography component="span" sx={{ fontWeight: 600, fontSize: 19 }}>
          Publisher Users &amp; Roles
        </Typography>
        <Typography color="text.secondary" sx={{ fontSize: 12, mt: 0.4 }}>
          {publisherName} · Publisher membership is independent of tenant access
        </Typography>
      </DialogTitle>
      <DialogContent sx={{ pt: "20px !important" }}>
        <Stack spacing={2}>
          {error && <Alert severity="error" onClose={() => setError("")}>{error}</Alert>}
          {success && <Alert severity="success" onClose={() => setSuccess("")}>{success}</Alert>}
          <Box sx={{ bgcolor: "#f7f9fa", border: "1px solid #d9e0e5", p: 2 }}>
            <Typography sx={{ fontWeight: 600, fontSize: 14, mb: 1.5 }}>
              Add existing AUGMIS user
            </Typography>
            <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "minmax(180px, 1fr) minmax(220px, 1fr) auto" }, gap: 1.5, alignItems: "start" }}>
              <TextField size="small" label="User email" value={email}
                onChange={(event) => setEmail(event.target.value)} />
              {roleSelect(addRoles, setAddRoles, "Publisher roles")}
              <Button variant="contained" disabled={Boolean(busyId) || !email.trim() || !addRoles.length}
                onClick={() => void handleAdd()}>Add user</Button>
            </Box>
          </Box>
          <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <Typography sx={{ fontWeight: 600 }}>Members ({members.length})</Typography>
            <Button size="small" onClick={() => void refresh()} disabled={loading || Boolean(busyId)}>Refresh</Button>
          </Box>
          {loading ? (
            <Box sx={{ display: "grid", placeItems: "center", py: 4 }}><CircularProgress size={28} /></Box>
          ) : members.length === 0 ? (
            <Typography color="text.secondary">No publisher memberships found.</Typography>
          ) : (
            <Box sx={{ border: "1px solid #d9e0e5", overflowX: "auto" }}>
              <Box sx={{ minWidth: 760 }}>
                {members.map((member) => {
                  const self = member.user.id === user?.id;
                  const owner = member.roles.some((role) => role.code === "publisher_owner");
                  const protectedTarget = self || (owner && !isPublisherOwner);
                  const isEditing = editingId === member.membershipId;
                  return (
                    <Box key={member.membershipId} sx={{ display: "grid", gridTemplateColumns: "minmax(190px,1.3fr) minmax(200px,1fr) 100px minmax(240px,1.4fr)", gap: 1, alignItems: "center", borderBottom: "1px solid #d9e0e5", px: 1.5, py: 1.5 }}>
                      <Box>
                        <Typography sx={{ fontSize: 13, fontWeight: 600 }}>
                          {member.user.firstName} {member.user.lastName} {self ? "(You)" : ""}
                        </Typography>
                        <Typography sx={{ fontSize: 11, color: "text.secondary" }}>{member.user.email}</Typography>
                        {member.user.status !== "active" && <Typography sx={{ color: "error.main", fontSize: 11 }}>Account {member.user.status}</Typography>}
                      </Box>
                      {isEditing ? roleSelect(editRoles, setEditRoles, "Roles") : (
                        <Typography sx={{ fontSize: 12 }}>{member.roles.map((r) => r.name).join(", ")}</Typography>
                      )}
                      <Chip size="small" variant="outlined"
                        color={member.status === "active" ? "success" : member.status === "suspended" ? "warning" : "default"}
                        label={member.status} sx={{ textTransform: "capitalize" }} />
                      <Stack direction="row" spacing={0.5} sx={{ flexWrap: "wrap", gap: 0.5 }}>
                        {isEditing ? (
                          <>
                            <Button size="small" variant="contained" disabled={!editRoles.length || Boolean(busyId)}
                              onClick={() => void run(member.membershipId,
                                () => changePublisherMemberRoles(publisherId, member.membershipId, editRoles), "Publisher roles updated.")}>Save</Button>
                            <Button size="small" disabled={Boolean(busyId)} onClick={() => setEditingId("")}>Cancel</Button>
                          </>
                        ) : (
                          <>
                            <Button size="small" disabled={protectedTarget || Boolean(busyId)}
                              onClick={() => { setEditingId(member.membershipId); setEditRoles(member.roles.map((r) => r.code)); }}>Roles</Button>
                            {member.status === "active" ? (
                              <Button size="small" color="warning" disabled={protectedTarget || Boolean(busyId)}
                                onClick={() => void run(member.membershipId,
                                  () => setPublisherMemberStatus(publisherId, member.membershipId, "suspend"), "Publisher user suspended.")}>Suspend</Button>
                            ) : (
                              <Button size="small" disabled={protectedTarget || Boolean(busyId)}
                                onClick={() => void run(member.membershipId,
                                  () => setPublisherMemberStatus(publisherId, member.membershipId, "activate"), "Publisher user activated.")}>Activate</Button>
                            )}
                            {member.status !== "revoked" && <Button size="small" color="error" disabled={protectedTarget || Boolean(busyId)}
                              onClick={() => {
                                if (window.confirm(`Revoke publisher access for ${member.user.email}?`)) {
                                  void run(member.membershipId,
                                    () => setPublisherMemberStatus(publisherId, member.membershipId, "revoke"), "Publisher access revoked.");
                                }
                              }}>Revoke</Button>}
                          </>
                        )}
                      </Stack>
                    </Box>
                  );
                })}
              </Box>
            </Box>
          )}
          <Typography sx={{ fontSize: 11, color: "text.secondary" }}>
            Only active Publisher Owners can assign or change Publisher Owner access.
            You cannot change your own membership or remove the last active Publisher Owner.
          </Typography>
        </Stack>
      </DialogContent>
      <DialogActions sx={{ borderTop: "1px solid", borderColor: "divider", px: 2.5, py: 1.5 }}>
        <Button onClick={onClose} disabled={Boolean(busyId)}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}
