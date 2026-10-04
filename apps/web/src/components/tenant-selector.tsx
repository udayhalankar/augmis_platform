// apps/web/src/components/tenant-selector.tsx

"use client";


import {
  CircularProgress,
  FormControl,
  MenuItem,
  Select,
  SelectChangeEvent,
  Stack,
  Typography,
} from "@mui/material";


import DomainOutlined
  from "@mui/icons-material/DomainOutlined";


import {
  useTenant,
} from "@/context/tenant-context";


export default function TenantSelector() {

  const {
    tenants,
    selectedTenantId,
    loading,
    error,
    selectTenant,
  } = useTenant();


  const handleChange = (
    event: SelectChangeEvent<string>
  ) => {

    selectTenant(
      event.target.value
    );
  };


  if (loading) {

    return (
      <Stack
        direction="row"
        spacing={1}
        sx={{
          alignItems: "center",
          minWidth: 180,
        }}
      >

        <CircularProgress
          size={16}
        />

        <Typography
          sx={{
            fontSize: 12,
            color:
              "text.secondary",
          }}
        >
          Loading tenants
        </Typography>

      </Stack>
    );
  }


  if (error) {

    return (
      <Typography
        sx={{
          fontSize: 12,
          color:
            "error.main",
        }}
      >
        Tenant unavailable
      </Typography>
    );
  }


  if (
    tenants.length === 0
  ) {

    return (
      <Typography
        sx={{
          fontSize: 12,
          color:
            "text.secondary",
        }}
      >
        No tenant access
      </Typography>
    );
  }


  return (
    <Stack
      direction="row"
      spacing={1}
      sx={{
        alignItems:
          "center",
      }}
    >

      <DomainOutlined
        sx={{
          fontSize: 19,
          color:
            "text.secondary",
        }}
      />


      <Typography
        sx={{
          fontSize: 11,
          fontWeight: 600,
          color:
            "text.secondary",
          whiteSpace:
            "nowrap",
        }}
      >
        TENANT
      </Typography>


      <FormControl
        size="small"
        sx={{
          minWidth: 210,
        }}
      >

        <Select
          value={
            selectedTenantId
          }
          onChange={
            handleChange
          }
          displayEmpty
          sx={{
            height: 36,

            bgcolor:
              "#ffffff",

            fontSize: 13,

            "& .MuiSelect-select":
              {
                py: 0.75,
              },
          }}
        >

          {tenants.map(
            (
              membership
            ) => (

              <MenuItem
                key={
                  membership
                    .tenant.id
                }
                value={
                  membership
                    .tenant.id
                }
              >

                <Stack
                  spacing={0.15}
                >

                  <Typography
                    sx={{
                      fontSize: 13,
                      fontWeight:
                        600,
                    }}
                  >
                    {
                      membership
                        .tenant
                        .name
                    }
                  </Typography>


                  <Typography
                    sx={{
                      fontSize: 10,
                      color:
                        "text.secondary",
                    }}
                  >
                    {
                      membership
                        .tenant
                        .slug
                    }
                  </Typography>

                </Stack>

              </MenuItem>

            )
          )}

        </Select>

      </FormControl>

    </Stack>
  );
}