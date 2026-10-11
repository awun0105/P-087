"""Shared acceptance policy for grouped video-input recipes."""

from src.models.contracts.input_assembly import RecipeGroup

# R2/R3 keep the exact map in input-run lineage for the registration operation;
# R4-R6 have their corresponding worker-stage consumers.
INPUT_ASSEMBLY_RUNNABLE_RECIPE_GROUPS = frozenset(
    {
        RecipeGroup.RGB_ONLY,
        RecipeGroup.REGISTERED_MAP,
        RecipeGroup.SINGLE_STATIC_CLOUD,
        RecipeGroup.SUPPLIED_TRAJECTORY,
        RecipeGroup.ESTIMATED_TRAJECTORY,
        RecipeGroup.SENSOR_GUIDED,
    }
)
