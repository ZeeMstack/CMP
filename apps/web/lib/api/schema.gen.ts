// GENERATED FILE -- do not edit by hand.
// Regenerate with: npm run api:types

export interface paths {
    "/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Health */
        get: operations["get_health_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/ready": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Ready */
        get: operations["get_ready_ready_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/memberships": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Create Membership */
        post: operations["create_membership_memberships_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Farms */
        get: operations["list_farms_farms_get"];
        put?: never;
        /** Create Farm */
        post: operations["create_farm_farms_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Farm */
        get: operations["get_farm_farms__farm_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/locations": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Create Location */
        post: operations["create_location_farms__farm_id__locations_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/locations/{parent_id}/bulk-children": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Bulk Create Children */
        post: operations["bulk_create_children_farms__farm_id__locations__parent_id__bulk_children_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/locations/tree": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Farm Tree */
        get: operations["get_farm_tree_farms__farm_id__locations_tree_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/locations/{location_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Location */
        get: operations["get_location_farms__farm_id__locations__location_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/locations/{location_id}/children": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Children */
        get: operations["list_children_farms__farm_id__locations__location_id__children_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/locations/{location_id}/path": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Path */
        get: operations["get_path_farms__farm_id__locations__location_id__path_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/locations/{location_id}/occupant": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Location Occupant */
        get: operations["get_location_occupant_farms__farm_id__locations__location_id__occupant_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/assets": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Assets */
        get: operations["list_assets_farms__farm_id__assets_get"];
        put?: never;
        /** Register Asset */
        post: operations["register_asset_farms__farm_id__assets_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/assets/{asset_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Asset */
        get: operations["get_asset_farms__farm_id__assets__asset_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/assets/{asset_id}/positions/generate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Generate Positions */
        post: operations["generate_positions_farms__farm_id__assets__asset_id__positions_generate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/assets/{asset_id}/positions/tree": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Positions Tree */
        get: operations["get_positions_tree_farms__farm_id__assets__asset_id__positions_tree_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/assets/{asset_id}/occupancy": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Asset Occupancy */
        get: operations["get_asset_occupancy_farms__farm_id__assets__asset_id__occupancy_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/assets/{asset_id}/movement-history": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Asset Movement History */
        get: operations["get_asset_movement_history_farms__farm_id__assets__asset_id__movement_history_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/assets/{asset_id}/resolved-location": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Asset Resolved Location */
        get: operations["get_asset_resolved_location_farms__farm_id__assets__asset_id__resolved_location_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/assets/{asset_id}/positions/{position_id}/occupant": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Position Occupant */
        get: operations["get_position_occupant_farms__farm_id__assets__asset_id__positions__position_id__occupant_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/carriers": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Carriers */
        get: operations["list_carriers_farms__farm_id__carriers_get"];
        put?: never;
        /** Register Carrier */
        post: operations["register_carrier_farms__farm_id__carriers_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/carriers/bulk": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Bulk Register Carriers */
        post: operations["bulk_register_carriers_farms__farm_id__carriers_bulk_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/carriers/{carrier_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Carrier */
        get: operations["get_carrier_farms__farm_id__carriers__carrier_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/carriers/{carrier_id}/occupancy": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Carrier Occupancy */
        get: operations["get_carrier_occupancy_farms__farm_id__carriers__carrier_id__occupancy_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/carriers/{carrier_id}/movement-history": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Carrier Movement History */
        get: operations["get_carrier_movement_history_farms__farm_id__carriers__carrier_id__movement_history_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/carriers/{carrier_id}/resolved-location": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Carrier Resolved Location */
        get: operations["get_carrier_resolved_location_farms__farm_id__carriers__carrier_id__resolved_location_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/movements": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Create Movement */
        post: operations["create_movement_farms__farm_id__movements_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/crops": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Crops */
        get: operations["list_crops_crops_get"];
        put?: never;
        /** Create Crop */
        post: operations["create_crop_crops_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/crops/{crop_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Crop */
        get: operations["get_crop_crops__crop_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/crops/{crop_id}/varieties": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Varieties */
        get: operations["list_varieties_crops__crop_id__varieties_get"];
        put?: never;
        /** Create Variety */
        post: operations["create_variety_crops__crop_id__varieties_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/crops/{crop_id}/varieties/{variety_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Variety */
        get: operations["get_variety_crops__crop_id__varieties__variety_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/production-systems": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Production Systems */
        get: operations["list_production_systems_production_systems_get"];
        put?: never;
        /** Create Production System */
        post: operations["create_production_system_production_systems_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/production-systems/{production_system_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Production System */
        get: operations["get_production_system_production_systems__production_system_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/workflows": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Workflows */
        get: operations["list_workflows_workflows_get"];
        put?: never;
        /** Create Workflow */
        post: operations["create_workflow_workflows_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/workflows/{workflow_id}/versions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Create Draft Version */
        post: operations["create_draft_version_workflows__workflow_id__versions_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/workflows/{workflow_id}/versions/{version_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Workflow Version */
        get: operations["get_workflow_version_workflows__workflow_id__versions__version_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/workflows/{workflow_id}/versions/{version_id}/stages": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Add Stage */
        post: operations["add_stage_workflows__workflow_id__versions__version_id__stages_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/workflows/{workflow_id}/versions/{version_id}/transitions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Add Transition */
        post: operations["add_transition_workflows__workflow_id__versions__version_id__transitions_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/workflows/{workflow_id}/versions/{version_id}/publish": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Publish Workflow Version */
        post: operations["publish_workflow_version_workflows__workflow_id__versions__version_id__publish_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/crop-batches": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Crop Batches */
        get: operations["list_crop_batches_farms__farm_id__crop_batches_get"];
        put?: never;
        /** Create Crop Batch */
        post: operations["create_crop_batch_farms__farm_id__crop_batches_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/crop-batches/{batch_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Crop Batch */
        get: operations["get_crop_batch_farms__farm_id__crop_batches__batch_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/crop-batches/{batch_id}/stage-transitions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Create Stage Transition */
        post: operations["create_stage_transition_farms__farm_id__crop_batches__batch_id__stage_transitions_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/crop-batches/{batch_id}/current-stage": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Current Stage */
        get: operations["get_current_stage_farms__farm_id__crop_batches__batch_id__current_stage_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/crop-batches/{batch_id}/stage-history": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Stage History */
        get: operations["get_stage_history_farms__farm_id__crop_batches__batch_id__stage_history_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/crop-batches/{batch_id}/stage-transitions/{transition_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Stage Transition */
        get: operations["get_stage_transition_farms__farm_id__crop_batches__batch_id__stage_transitions__transition_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/crop-batches/{batch_id}/split": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Split Crop Batch */
        post: operations["split_crop_batch_farms__farm_id__crop_batches__batch_id__split_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/crop-batch-merges": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Merge Crop Batches */
        post: operations["merge_crop_batches_farms__farm_id__crop_batch_merges_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/batch-derivations/{derivation_event_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Batch Derivation */
        get: operations["get_batch_derivation_farms__farm_id__batch_derivations__derivation_event_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/crop-batches/{batch_id}/lineage": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Crop Batch Lineage */
        get: operations["get_crop_batch_lineage_farms__farm_id__crop_batches__batch_id__lineage_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/seed-lots": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Seed Lots */
        get: operations["list_seed_lots_farms__farm_id__seed_lots_get"];
        put?: never;
        /** Register Seed Lot */
        post: operations["register_seed_lot_farms__farm_id__seed_lots_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/seed-lots/{seed_lot_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Seed Lot */
        get: operations["get_seed_lot_farms__farm_id__seed_lots__seed_lot_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/crop-batches/{batch_id}/sowings": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Sowings */
        get: operations["list_sowings_farms__farm_id__crop_batches__batch_id__sowings_get"];
        put?: never;
        /** Sow Batch */
        post: operations["sow_batch_farms__farm_id__crop_batches__batch_id__sowings_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/crop-batches/{batch_id}/sowings/{sowing_event_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Sowing */
        get: operations["get_sowing_farms__farm_id__crop_batches__batch_id__sowings__sowing_event_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/crop-batches/{batch_id}/carriers": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Batch Carriers */
        get: operations["list_batch_carriers_farms__farm_id__crop_batches__batch_id__carriers_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/carriers/{carrier_id}/batch-assignment": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Carrier Batch Assignment */
        get: operations["get_carrier_batch_assignment_farms__farm_id__carriers__carrier_id__batch_assignment_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/observation-definitions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Observation Definitions */
        get: operations["list_observation_definitions_observation_definitions_get"];
        put?: never;
        /** Create Observation Definition */
        post: operations["create_observation_definition_observation_definitions_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/observation-definitions/{definition_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Observation Definition */
        get: operations["get_observation_definition_observation_definitions__definition_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/crop-batches/{batch_id}/observations": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Observations */
        get: operations["list_observations_farms__farm_id__crop_batches__batch_id__observations_get"];
        put?: never;
        /** Record Observation */
        post: operations["record_observation_farms__farm_id__crop_batches__batch_id__observations_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/crop-batches/{batch_id}/observations/{observation_event_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Observation */
        get: operations["get_observation_farms__farm_id__crop_batches__batch_id__observations__observation_event_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/crop-batches/{batch_id}/quality-holds": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Quality Holds */
        get: operations["list_quality_holds_farms__farm_id__crop_batches__batch_id__quality_holds_get"];
        put?: never;
        /** Place Quality Hold */
        post: operations["place_quality_hold_farms__farm_id__crop_batches__batch_id__quality_holds_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/crop-batches/{batch_id}/quality-holds/{hold_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Quality Hold */
        get: operations["get_quality_hold_farms__farm_id__crop_batches__batch_id__quality_holds__hold_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/crop-batches/{batch_id}/quality-holds/{hold_id}/release": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Release Quality Hold */
        post: operations["release_quality_hold_farms__farm_id__crop_batches__batch_id__quality_holds__hold_id__release_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/crop-batches/{batch_id}/transplants": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Transplants */
        get: operations["list_transplants_farms__farm_id__crop_batches__batch_id__transplants_get"];
        put?: never;
        /** Record Transplant */
        post: operations["record_transplant_farms__farm_id__crop_batches__batch_id__transplants_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/crop-batches/{batch_id}/transplants/{transplant_event_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Transplant */
        get: operations["get_transplant_farms__farm_id__crop_batches__batch_id__transplants__transplant_event_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/crop-batches/{batch_id}/harvests": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Harvests */
        get: operations["list_harvests_farms__farm_id__crop_batches__batch_id__harvests_get"];
        put?: never;
        /** Record Harvest */
        post: operations["record_harvest_farms__farm_id__crop_batches__batch_id__harvests_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/crop-batches/{batch_id}/harvests/{harvest_event_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Harvest */
        get: operations["get_harvest_farms__farm_id__crop_batches__batch_id__harvests__harvest_event_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/harvested-produce-lots": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Harvested Produce Lots */
        get: operations["list_harvested_produce_lots_farms__farm_id__harvested_produce_lots_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/harvested-produce-lots/{produce_lot_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Harvested Produce Lot */
        get: operations["get_harvested_produce_lot_farms__farm_id__harvested_produce_lots__produce_lot_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/harvested-produce-lots/{produce_lot_id}/ledger": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Produce Lot Ledger */
        get: operations["get_produce_lot_ledger_farms__farm_id__harvested_produce_lots__produce_lot_id__ledger_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/harvested-produce-lots/{produce_lot_id}/balance": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Produce Lot Balance */
        get: operations["get_produce_lot_balance_farms__farm_id__harvested_produce_lots__produce_lot_id__balance_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/packing-events": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Packing Events */
        get: operations["list_packing_events_farms__farm_id__packing_events_get"];
        put?: never;
        /** Record Packing */
        post: operations["record_packing_farms__farm_id__packing_events_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/packing-events/{packing_event_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Packing Event */
        get: operations["get_packing_event_farms__farm_id__packing_events__packing_event_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/finished-goods-lots": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Finished Goods Lots */
        get: operations["list_finished_goods_lots_farms__farm_id__finished_goods_lots_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/finished-goods-lots/{finished_goods_lot_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Finished Goods Lot */
        get: operations["get_finished_goods_lot_farms__farm_id__finished_goods_lots__finished_goods_lot_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/finished-goods-lots/{finished_goods_lot_id}/ledger": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Finished Goods Ledger */
        get: operations["get_finished_goods_ledger_farms__farm_id__finished_goods_lots__finished_goods_lot_id__ledger_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/finished-goods-lots/{finished_goods_lot_id}/balance": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Finished Goods Balance */
        get: operations["get_finished_goods_balance_farms__farm_id__finished_goods_lots__finished_goods_lot_id__balance_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/dispatches": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Dispatch Events */
        get: operations["list_dispatch_events_farms__farm_id__dispatches_get"];
        put?: never;
        /** Record Dispatch */
        post: operations["record_dispatch_farms__farm_id__dispatches_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/dispatches/{dispatch_event_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Dispatch Event */
        get: operations["get_dispatch_event_farms__farm_id__dispatches__dispatch_event_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/finished-goods-storage-movements": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Record Movement */
        post: operations["record_movement_farms__farm_id__finished_goods_storage_movements_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/finished-goods-lots/{finished_goods_lot_id}/storage-movements": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Storage Movements */
        get: operations["get_storage_movements_farms__farm_id__finished_goods_lots__finished_goods_lot_id__storage_movements_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/finished-goods-lots/{finished_goods_lot_id}/placements": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Placement */
        get: operations["get_placement_farms__farm_id__finished_goods_lots__finished_goods_lot_id__placements_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/locations/{location_id}/finished-goods-inventory": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Location Inventory */
        get: operations["get_location_inventory_farms__farm_id__locations__location_id__finished_goods_inventory_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/traceability/finished-goods-lots/{finished_goods_lot_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Finished Goods Lot Trace */
        get: operations["get_finished_goods_lot_trace_farms__farm_id__traceability_finished_goods_lots__finished_goods_lot_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/traceability/crop-batches/{crop_batch_id}/impact": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Crop Batch Impact */
        get: operations["get_crop_batch_impact_farms__farm_id__traceability_crop_batches__crop_batch_id__impact_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/traceability/harvested-produce-lots/{produce_lot_id}/impact": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Harvested Produce Lot Impact */
        get: operations["get_harvested_produce_lot_impact_farms__farm_id__traceability_harvested_produce_lots__produce_lot_id__impact_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/recall-cases": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Recall Cases */
        get: operations["list_recall_cases_farms__farm_id__recall_cases_get"];
        put?: never;
        /** Open Recall Case */
        post: operations["open_recall_case_farms__farm_id__recall_cases_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/recall-cases/{recall_case_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Recall Case */
        get: operations["get_recall_case_farms__farm_id__recall_cases__recall_case_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/recall-cases/{recall_case_id}/close": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Close Recall Case */
        post: operations["close_recall_case_farms__farm_id__recall_cases__recall_case_id__close_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/dev/bootstrap/tenants": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Bootstrap Tenant */
        post: operations["bootstrap_tenant_dev_bootstrap_tenants_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/dev/bootstrap/users": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Bootstrap User */
        post: operations["bootstrap_user_dev_bootstrap_users_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/dev/bootstrap/memberships": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Bootstrap Membership
         * @description Development-only: creates a tenant's first membership. No active
         *     membership is required to call this — that's the whole point of a
         *     bootstrap route. `POST /memberships` (not under /dev/bootstrap) is for
         *     an already-active member to add further members.
         */
        post: operations["bootstrap_membership_dev_bootstrap_memberships_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Root */
        get: operations["root__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** AssetCreate */
        AssetCreate: {
            /** Asset Type Code */
            asset_type_code: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
            /** Commissioned Date */
            commissioned_date?: string | null;
        };
        /** AssetPositionRead */
        AssetPositionRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Asset Id
             * Format: uuid
             */
            asset_id: string;
            /** Parent Position Id */
            parent_position_id: string | null;
            /** Position Kind */
            position_kind: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
        };
        /** AssetPositionTreeNode */
        AssetPositionTreeNode: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Position Kind */
            position_kind: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
            /**
             * Children
             * @default []
             */
            children: components["schemas"]["AssetPositionTreeNode"][];
        };
        /** AssetPositionsGenerate */
        AssetPositionsGenerate: {
            /** Shelf Count */
            shelf_count: number;
            /** Slots Per Shelf */
            slots_per_shelf: number;
            /** Shelf Prefix */
            shelf_prefix: string;
            /** Slot Prefix */
            slot_prefix: string;
            /** Shelf Pad Width */
            shelf_pad_width: number;
            /** Slot Pad Width */
            slot_pad_width: number;
        };
        /** AssetRead */
        AssetRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /**
             * Farm Id
             * Format: uuid
             */
            farm_id: string;
            /**
             * Asset Type Id
             * Format: uuid
             */
            asset_type_id: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
            /** Status */
            status: string;
            /** Commissioned Date */
            commissioned_date: string | null;
            /** Retired Date */
            retired_date: string | null;
        };
        /** BatchAssignmentTransferRead */
        BatchAssignmentTransferRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            carrier: components["schemas"]["CarrierRefSummary"];
            source_batch: components["schemas"]["BatchSummary"];
            output_batch: components["schemas"]["BatchSummary"];
            /**
             * Released Source Assignment Id
             * Format: uuid
             */
            released_source_assignment_id: string;
            /**
             * Opened Destination Assignment Id
             * Format: uuid
             */
            opened_destination_assignment_id: string;
            /** Transferred Plant Count */
            transferred_plant_count: number;
        };
        /** BatchCarrierAssignmentRead */
        BatchCarrierAssignmentRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Batch Id
             * Format: uuid
             */
            batch_id: string;
            carrier: components["schemas"]["CarrierSummary"];
            /**
             * Assigned Effective Time
             * Format: date-time
             */
            assigned_effective_time: string;
            /** Released Effective Time */
            released_effective_time: string | null;
            /** Opening Sowing Event Id */
            opening_sowing_event_id: string | null;
            /** Opening Transplant Event Id */
            opening_transplant_event_id: string | null;
            /** Released By Transplant Event Id */
            released_by_transplant_event_id: string | null;
            /** Opening Batch Derivation Event Id */
            opening_batch_derivation_event_id: string | null;
            /** Released By Batch Derivation Event Id */
            released_by_batch_derivation_event_id: string | null;
        };
        /** BatchDerivationEventRead */
        BatchDerivationEventRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /**
             * Farm Id
             * Format: uuid
             */
            farm_id: string;
            /** Derivation Kind */
            derivation_kind: string;
            workflow: components["schemas"]["WorkflowSummary"];
            /**
             * Workflow Version Id
             * Format: uuid
             */
            workflow_version_id: string;
            inherited_stage: components["schemas"]["StageSummary"];
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /**
             * Recorded At
             * Format: date-time
             */
            recorded_at: string;
            /**
             * Actor User Id
             * Format: uuid
             */
            actor_user_id: string;
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            /** Note */
            note: string | null;
            /** Sources */
            sources: components["schemas"]["BatchDerivationSourceRead"][];
            /** Outputs */
            outputs: components["schemas"]["BatchDerivationOutputRead"][];
            /** Transfers */
            transfers: components["schemas"]["BatchAssignmentTransferRead"][];
            /** Total Source Plant Count */
            total_source_plant_count: number;
            /** Total Output Plant Count */
            total_output_plant_count: number;
            /** Total Carrier Transfer Count */
            total_carrier_transfer_count: number;
        };
        /** BatchDerivationOutputRead */
        BatchDerivationOutputRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            output_batch: components["schemas"]["BatchSummary"];
            /** Recorded Plant Quantity Total */
            recorded_plant_quantity_total: number;
            /** Recorded Carrier Assignment Count */
            recorded_carrier_assignment_count: number;
        };
        /** BatchDerivationSourceRead */
        BatchDerivationSourceRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            source_batch: components["schemas"]["BatchSummary"];
            /**
             * Source Batch Stage Run Id
             * Format: uuid
             */
            source_batch_stage_run_id: string;
            /** Recorded Plant Quantity Total */
            recorded_plant_quantity_total: number;
            /** Recorded Carrier Assignment Count */
            recorded_carrier_assignment_count: number;
        };
        /** BatchLineageEventRead */
        BatchLineageEventRead: {
            /**
             * Derivation Event Id
             * Format: uuid
             */
            derivation_event_id: string;
            /** Derivation Kind */
            derivation_kind: string;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            batch: components["schemas"]["BatchSummary"];
            /** Recorded Plant Quantity Total */
            recorded_plant_quantity_total: number;
            /** Recorded Carrier Assignment Count */
            recorded_carrier_assignment_count: number;
        };
        /** BatchLineageRead */
        BatchLineageRead: {
            /**
             * Batch Id
             * Format: uuid
             */
            batch_id: string;
            /** Parents */
            parents: components["schemas"]["BatchLineageEventRead"][];
            /** Children */
            children: components["schemas"]["BatchLineageEventRead"][];
        };
        /** BatchMergeCreate */
        BatchMergeCreate: {
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /** Note */
            note?: string | null;
            /** Source Batch Ids */
            source_batch_ids: string[];
            /** Output Batch Code */
            output_batch_code: string;
        };
        /** BatchSplitCreate */
        BatchSplitCreate: {
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /** Note */
            note?: string | null;
            /** Outputs */
            outputs: components["schemas"]["SplitOutputIn"][];
        };
        /** BatchStageRunRead */
        BatchStageRunRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            stage: components["schemas"]["StageSummary"];
            /**
             * Entered Effective Time
             * Format: date-time
             */
            entered_effective_time: string;
            /** Exited Effective Time */
            exited_effective_time: string | null;
        };
        /** BatchStageTransitionCreate */
        BatchStageTransitionCreate: {
            /**
             * Configured Transition Id
             * Format: uuid
             */
            configured_transition_id: string;
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /** Reason */
            reason?: string | null;
        };
        /** BatchStageTransitionRead */
        BatchStageTransitionRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /**
             * Farm Id
             * Format: uuid
             */
            farm_id: string;
            /**
             * Batch Id
             * Format: uuid
             */
            batch_id: string;
            /**
             * Workflow Version Id
             * Format: uuid
             */
            workflow_version_id: string;
            /** Command Kind */
            command_kind: string;
            /** Source Stage Id */
            source_stage_id: string | null;
            /**
             * Destination Stage Id
             * Format: uuid
             */
            destination_stage_id: string;
            /** Configured Transition Id */
            configured_transition_id: string | null;
            /** Batch Derivation Event Id */
            batch_derivation_event_id: string | null;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /**
             * Recorded Time
             * Format: date-time
             */
            recorded_time: string;
            /**
             * Actor User Id
             * Format: uuid
             */
            actor_user_id: string;
            /** Client Command Id */
            client_command_id: string | null;
            /** Reason */
            reason: string | null;
        };
        /** BatchSummary */
        BatchSummary: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Code */
            code: string;
        };
        /**
         * BootstrapMembershipCreate
         * @description Development-only: creates a membership without requiring an existing
         *     active membership, to bootstrap a tenant's first member.
         */
        BootstrapMembershipCreate: {
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /**
             * User Id
             * Format: uuid
             */
            user_id: string;
            /** Role Code */
            role_code: string;
        };
        /** CarrierBulkCreate */
        CarrierBulkCreate: {
            /** Carrier Type Code */
            carrier_type_code: string;
            /** Code Prefix */
            code_prefix: string;
            /** Start */
            start: number;
            /** End */
            end: number;
            /** Pad Width */
            pad_width: number;
        };
        /** CarrierCreate */
        CarrierCreate: {
            /** Carrier Type Code */
            carrier_type_code: string;
            /** Code */
            code: string;
            /** Issued Date */
            issued_date?: string | null;
        };
        /** CarrierRead */
        CarrierRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /**
             * Farm Id
             * Format: uuid
             */
            farm_id: string;
            /**
             * Carrier Type Id
             * Format: uuid
             */
            carrier_type_id: string;
            /** Code */
            code: string;
            /** Status */
            status: string;
            /** Issued Date */
            issued_date: string | null;
            /** Retired Date */
            retired_date: string | null;
        };
        /** CarrierRefSummary */
        CarrierRefSummary: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Code */
            code: string;
        };
        /** CarrierSummary */
        CarrierSummary: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Code */
            code: string;
            carrier_type: components["schemas"]["CarrierTypeSummary"];
        };
        /** CarrierTypeSummary */
        CarrierTypeSummary: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
        };
        /** Completeness */
        Completeness: {
            /** Trace Complete */
            trace_complete: boolean;
            /**
             * Limitations
             * @default []
             */
            limitations: components["schemas"]["Limitation"][];
            /**
             * Capability Limitations
             * @default []
             */
            capability_limitations: string[];
        };
        /** ContainingAssetRef */
        ContainingAssetRef: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
        };
        /** CropBatchCreate */
        CropBatchCreate: {
            /** Code */
            code: string;
            /**
             * Workflow Id
             * Format: uuid
             */
            workflow_id: string;
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
        };
        /** CropBatchImpactRead */
        CropBatchImpactRead: {
            /**
             * Subject Batch Id
             * Format: uuid
             */
            subject_batch_id: string;
            /** Subject Batch Code */
            subject_batch_code: string;
            lineage: components["schemas"]["Lineage"];
            /** Harvest Events */
            harvest_events: components["schemas"]["app__schemas__traceability__HarvestEventRead"][];
            /** Produce Lots */
            produce_lots: components["schemas"]["app__schemas__traceability__HarvestedProduceLotRead"][];
            /** Packing Inputs */
            packing_inputs: components["schemas"]["app__schemas__traceability__PackingInputLineRead"][];
            /** Finished Goods */
            finished_goods: components["schemas"]["FinishedGoodsLotImpactRead"][];
            /** Storage */
            storage: components["schemas"]["app__schemas__traceability__LocationBalanceRead"][];
            /** Dispatches */
            dispatches: components["schemas"]["app__schemas__traceability__DispatchLineRead"][];
            summary: components["schemas"]["ImpactSummary"];
            completeness: components["schemas"]["Completeness"];
        };
        /** CropBatchNode */
        CropBatchNode: {
            /**
             * Batch Id
             * Format: uuid
             */
            batch_id: string;
            /** Code */
            code: string;
            /** State */
            state: string;
            /**
             * Created Effective Time
             * Format: date-time
             */
            created_effective_time: string;
            /** Transformation Type */
            transformation_type: string;
            /** Derivation Event Id */
            derivation_event_id?: string | null;
        };
        /** CropBatchRead */
        CropBatchRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /**
             * Farm Id
             * Format: uuid
             */
            farm_id: string;
            /** Code */
            code: string;
            workflow: components["schemas"]["WorkflowSummary"];
            /**
             * Workflow Version Id
             * Format: uuid
             */
            workflow_version_id: string;
            /** Version Number */
            version_number: number;
            crop: components["schemas"]["CropSummary"];
            variety: components["schemas"]["VarietySummary"] | null;
            production_system: components["schemas"]["ProductionSystemSummary"];
            /** State */
            state: string;
            current_stage: components["schemas"]["StageSummary"];
            /**
             * Created Effective Time
             * Format: date-time
             */
            created_effective_time: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Closed Effective Time */
            closed_effective_time: string | null;
            /** Superseded Effective Time */
            superseded_effective_time: string | null;
            /** Superseded By Batch Derivation Event Id */
            superseded_by_batch_derivation_event_id: string | null;
            /** Created By Batch Derivation Event Id */
            created_by_batch_derivation_event_id: string | null;
        };
        /** CropCreate */
        CropCreate: {
            /** Code */
            code: string;
            /** Common Name */
            common_name: string;
            /** Scientific Name */
            scientific_name?: string | null;
            /** Crop Category */
            crop_category: string;
        };
        /** CropRead */
        CropRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /** Code */
            code: string;
            /** Common Name */
            common_name: string;
            /** Scientific Name */
            scientific_name: string | null;
            /** Crop Category */
            crop_category: string;
            /** Status */
            status: string;
        };
        /** CropSummary */
        CropSummary: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Code */
            code: string;
            /** Common Name */
            common_name: string;
        };
        /** CurrentStageRead */
        CurrentStageRead: {
            /**
             * Batch Id
             * Format: uuid
             */
            batch_id: string;
            current_stage: components["schemas"]["StageSummary"];
            /**
             * Entered Effective Time
             * Format: date-time
             */
            entered_effective_time: string;
        };
        /** DispatchEventCreate */
        DispatchEventCreate: {
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /** Code */
            code: string;
            /** External Reference */
            external_reference?: string | null;
            /** Note */
            note?: string | null;
            /** Lines */
            lines: components["schemas"]["DispatchLineIn"][];
        };
        /** DispatchEventRead */
        DispatchEventRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /**
             * Farm Id
             * Format: uuid
             */
            farm_id: string;
            /** Code */
            code: string;
            /** Lines */
            lines: components["schemas"]["app__schemas__dispatch__DispatchLineRead"][];
            /** Total Dispatched Weight Kg */
            total_dispatched_weight_kg: string;
            /** Total Dispatched Package Count */
            total_dispatched_package_count: number;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /**
             * Recorded Time
             * Format: date-time
             */
            recorded_time: string;
            /**
             * Actor User Id
             * Format: uuid
             */
            actor_user_id: string;
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            /** External Reference */
            external_reference: string | null;
            /** Note */
            note: string | null;
        };
        /** DispatchLineIn */
        DispatchLineIn: {
            /**
             * Finished Goods Lot Id
             * Format: uuid
             */
            finished_goods_lot_id: string;
            /** Dispatched Weight Kg */
            dispatched_weight_kg: number | string;
            /** Dispatched Package Count */
            dispatched_package_count: number;
        };
        /** FarmCreate */
        FarmCreate: {
            /** Code */
            code: string;
            /** Name */
            name: string;
            /** Country Code */
            country_code: string;
            /** City Region */
            city_region?: string | null;
            /** Timezone */
            timezone: string;
        };
        /** FarmRead */
        FarmRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
            /** Country Code */
            country_code: string;
            /** City Region */
            city_region: string | null;
            /** Timezone */
            timezone: string;
            /** Status */
            status: string;
        };
        /** FinishedGoodsBalanceRead */
        FinishedGoodsBalanceRead: {
            /**
             * Finished Goods Lot Id
             * Format: uuid
             */
            finished_goods_lot_id: string;
            /** Finished Goods Lot Code */
            finished_goods_lot_code: string;
            /** Received Weight Kg */
            received_weight_kg: string;
            /** Available Weight Kg */
            available_weight_kg: string;
            /** Received Package Count */
            received_package_count: number;
            /** Available Package Count */
            available_package_count: number;
            /** Entry Count */
            entry_count: number;
            /**
             * Last Effective Time
             * Format: date-time
             */
            last_effective_time: string;
        };
        /** FinishedGoodsLedgerEntryRead */
        FinishedGoodsLedgerEntryRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Entry Kind */
            entry_kind: string;
            /**
             * Finished Goods Lot Id
             * Format: uuid
             */
            finished_goods_lot_id: string;
            /** Finished Goods Lot Code */
            finished_goods_lot_code: string;
            /** Packing Event Id */
            packing_event_id: string | null;
            /** Dispatch Line Id */
            dispatch_line_id: string | null;
            /**
             * Actor User Id
             * Format: uuid
             */
            actor_user_id: string;
            /** Weight Delta Kg */
            weight_delta_kg: string;
            /** Package Count Delta */
            package_count_delta: number;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /**
             * Recorded Time
             * Format: date-time
             */
            recorded_time: string;
            /** Note */
            note: string | null;
        };
        /** FinishedGoodsLotImpactRead */
        FinishedGoodsLotImpactRead: {
            /**
             * Finished Goods Lot Id
             * Format: uuid
             */
            finished_goods_lot_id: string;
            /** Code */
            code: string;
            /**
             * Packing Event Id
             * Format: uuid
             */
            packing_event_id: string;
            /** Net Packed Weight Kg */
            net_packed_weight_kg: string;
            /** Package Count */
            package_count: number;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /** Available Weight Kg */
            available_weight_kg: string;
            /** Available Package Count */
            available_package_count: number;
            /** Placed Weight Kg */
            placed_weight_kg: string;
            /** Placed Package Count */
            placed_package_count: number;
            /** Unplaced Weight Kg */
            unplaced_weight_kg: string;
            /** Unplaced Package Count */
            unplaced_package_count: number;
            /** Source Input Weight Kg */
            source_input_weight_kg: string;
            /** Source Input Whole Unit Count */
            source_input_whole_unit_count: number | null;
            /** Potentially Affected Available Weight Kg */
            potentially_affected_available_weight_kg: string;
            /** Potentially Affected Available Package Count */
            potentially_affected_available_package_count: number;
            /** Potentially Affected Placed Weight Kg */
            potentially_affected_placed_weight_kg: string;
            /** Potentially Affected Placed Package Count */
            potentially_affected_placed_package_count: number;
            /** Potentially Affected Unplaced Weight Kg */
            potentially_affected_unplaced_weight_kg: string;
            /** Potentially Affected Unplaced Package Count */
            potentially_affected_unplaced_package_count: number;
            /** Potentially Affected Dispatched Weight Kg */
            potentially_affected_dispatched_weight_kg: string;
            /** Potentially Affected Dispatched Package Count */
            potentially_affected_dispatched_package_count: number;
        };
        /** FinishedGoodsLotSummary */
        FinishedGoodsLotSummary: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Code */
            code: string;
            /** Net Packed Weight Kg */
            net_packed_weight_kg: string;
            /** Package Count */
            package_count: number;
        };
        /** FinishedGoodsLotTraceRead */
        FinishedGoodsLotTraceRead: {
            subject: components["schemas"]["app__schemas__traceability__FinishedGoodsLotRead"];
            packing_event: components["schemas"]["app__schemas__traceability__PackingEventRead"];
            /** Packing Inputs */
            packing_inputs: components["schemas"]["app__schemas__traceability__PackingInputLineRead"][];
            /** Produce Lots */
            produce_lots: components["schemas"]["app__schemas__traceability__HarvestedProduceLotRead"][];
            /** Harvest Events */
            harvest_events: components["schemas"]["app__schemas__traceability__HarvestEventRead"][];
            lineage: components["schemas"]["Lineage"];
            /** Seed Origins */
            seed_origins: components["schemas"]["SeedOrigin"][];
            /** Storage Movements */
            storage_movements: components["schemas"]["StorageMovementRead"][];
            /** Dispatches */
            dispatches: components["schemas"]["app__schemas__traceability__DispatchLineRead"][];
            /** Quality */
            quality: components["schemas"]["app__schemas__traceability__QualityHoldRead"][];
            completeness: components["schemas"]["Completeness"];
        };
        /** FinishedGoodsPlacementRead */
        FinishedGoodsPlacementRead: {
            /**
             * Finished Goods Lot Id
             * Format: uuid
             */
            finished_goods_lot_id: string;
            /** Finished Goods Lot Code */
            finished_goods_lot_code: string;
            /** Available Weight Kg */
            available_weight_kg: string;
            /** Available Package Count */
            available_package_count: number;
            /** Total Placed Weight Kg */
            total_placed_weight_kg: string;
            /** Total Placed Package Count */
            total_placed_package_count: number;
            /** Unplaced Weight Kg */
            unplaced_weight_kg: string;
            /** Unplaced Package Count */
            unplaced_package_count: number;
            /** Locations */
            locations: components["schemas"]["app__schemas__finished_goods_storage__LocationBalanceRead"][];
        };
        /** FinishedGoodsStorageMovementCreate */
        FinishedGoodsStorageMovementCreate: {
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /**
             * Finished Goods Lot Id
             * Format: uuid
             */
            finished_goods_lot_id: string;
            /** Movement Kind */
            movement_kind: string;
            /** Source Location Id */
            source_location_id?: string | null;
            /** Destination Location Id */
            destination_location_id?: string | null;
            /** Moved Weight Kg */
            moved_weight_kg: number | string;
            /** Moved Package Count */
            moved_package_count: number;
            /** Note */
            note?: string | null;
        };
        /** FinishedGoodsStorageMovementRead */
        FinishedGoodsStorageMovementRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /**
             * Farm Id
             * Format: uuid
             */
            farm_id: string;
            /**
             * Finished Goods Lot Id
             * Format: uuid
             */
            finished_goods_lot_id: string;
            /** Movement Kind */
            movement_kind: string;
            /** Source Location Id */
            source_location_id: string | null;
            /** Destination Location Id */
            destination_location_id: string | null;
            /** Moved Weight Kg */
            moved_weight_kg: string;
            /** Moved Package Count */
            moved_package_count: number;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /**
             * Recorded Time
             * Format: date-time
             */
            recorded_time: string;
            /**
             * Actor User Id
             * Format: uuid
             */
            actor_user_id: string;
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            /** Note */
            note: string | null;
        };
        /** FrozenScopeRead */
        FrozenScopeRead: {
            /** Crop Batch Ids */
            crop_batch_ids: string[];
            /** Harvested Produce Lot Ids */
            harvested_produce_lot_ids: string[];
            /** Finished Goods Lot Ids */
            finished_goods_lot_ids: string[];
        };
        /** GerminationCheckIn */
        GerminationCheckIn: {
            /**
             * Batch Carrier Assignment Id
             * Format: uuid
             */
            batch_carrier_assignment_id: string;
            /** Inspected Site Count */
            inspected_site_count: number;
            /** Normal Germinated Site Count */
            normal_germinated_site_count: number;
            /** Abnormal Germinated Site Count */
            abnormal_germinated_site_count: number;
            /** Failed Site Count */
            failed_site_count: number;
            /** Note */
            note?: string | null;
        };
        /** GerminationCheckRead */
        GerminationCheckRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            carrier: components["schemas"]["CarrierSummary"];
            /**
             * Batch Carrier Assignment Id
             * Format: uuid
             */
            batch_carrier_assignment_id: string;
            /** Inspected Site Count */
            inspected_site_count: number;
            /** Normal Germinated Site Count */
            normal_germinated_site_count: number;
            /** Abnormal Germinated Site Count */
            abnormal_germinated_site_count: number;
            /** Failed Site Count */
            failed_site_count: number;
            /** Unresolved Site Count */
            unresolved_site_count: number;
            /** Total Germinated Site Count */
            total_germinated_site_count: number;
            /** Germination Percentage */
            germination_percentage: string;
            /** Note */
            note: string | null;
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** HarvestEventCreate */
        HarvestEventCreate: {
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /** Produce Lot Code */
            produce_lot_code: string;
            /** Note */
            note?: string | null;
            /** Source Lines */
            source_lines: components["schemas"]["HarvestSourceLineIn"][];
        };
        /** HarvestSourceLineIn */
        HarvestSourceLineIn: {
            /**
             * Batch Carrier Assignment Id
             * Format: uuid
             */
            batch_carrier_assignment_id: string;
            /** Harvested Weight Kg */
            harvested_weight_kg: number | string;
            /** Whole Unit Count */
            whole_unit_count?: number | null;
            /** Note */
            note?: string | null;
        };
        /** HarvestSourceLineRead */
        HarvestSourceLineRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Batch Carrier Assignment Id
             * Format: uuid
             */
            batch_carrier_assignment_id: string;
            carrier: components["schemas"]["CarrierSummary"];
            /** Opening Kind */
            opening_kind: string;
            /**
             * Opening Id
             * Format: uuid
             */
            opening_id: string;
            /** Harvested Weight Kg */
            harvested_weight_kg: string;
            /** Whole Unit Count */
            whole_unit_count: number | null;
            /** Note */
            note: string | null;
        };
        /** HarvestedProduceLotImpactRead */
        HarvestedProduceLotImpactRead: {
            /**
             * Subject Harvested Produce Lot Id
             * Format: uuid
             */
            subject_harvested_produce_lot_id: string;
            /** Subject Harvested Produce Lot Code */
            subject_harvested_produce_lot_code: string;
            /** Produce Lots */
            produce_lots: components["schemas"]["app__schemas__traceability__HarvestedProduceLotRead"][];
            /** Packing Inputs */
            packing_inputs: components["schemas"]["app__schemas__traceability__PackingInputLineRead"][];
            /** Finished Goods */
            finished_goods: components["schemas"]["FinishedGoodsLotImpactRead"][];
            /** Storage */
            storage: components["schemas"]["app__schemas__traceability__LocationBalanceRead"][];
            /** Dispatches */
            dispatches: components["schemas"]["app__schemas__traceability__DispatchLineRead"][];
            summary: components["schemas"]["ImpactSummary"];
            completeness: components["schemas"]["Completeness"];
        };
        /** ImpactSummary */
        ImpactSummary: {
            /** Affected Crop Batch Count */
            affected_crop_batch_count: number;
            /** Affected Harvested Produce Lot Count */
            affected_harvested_produce_lot_count: number;
            /** Affected Finished Goods Lot Count */
            affected_finished_goods_lot_count: number;
            /** Affected Dispatch Event Count */
            affected_dispatch_event_count: number;
            /** Potentially Affected Available Weight Kg */
            potentially_affected_available_weight_kg: string;
            /** Potentially Affected Available Package Count */
            potentially_affected_available_package_count: number;
            /** Potentially Affected Placed Weight Kg */
            potentially_affected_placed_weight_kg: string;
            /** Potentially Affected Placed Package Count */
            potentially_affected_placed_package_count: number;
            /** Potentially Affected Unplaced Weight Kg */
            potentially_affected_unplaced_weight_kg: string;
            /** Potentially Affected Unplaced Package Count */
            potentially_affected_unplaced_package_count: number;
            /** Potentially Affected Dispatched Weight Kg */
            potentially_affected_dispatched_weight_kg: string;
            /** Potentially Affected Dispatched Package Count */
            potentially_affected_dispatched_package_count: number;
        };
        /** Limitation */
        Limitation: {
            /** Code */
            code: string;
            /** Message */
            message: string;
        };
        /** Lineage */
        Lineage: {
            /** Batches */
            batches: components["schemas"]["CropBatchNode"][];
            /** Edges */
            edges: components["schemas"]["LineageEdge"][];
        };
        /** LineageEdge */
        LineageEdge: {
            /**
             * Parent Batch Id
             * Format: uuid
             */
            parent_batch_id: string;
            /**
             * Child Batch Id
             * Format: uuid
             */
            child_batch_id: string;
            /**
             * Derivation Event Id
             * Format: uuid
             */
            derivation_event_id: string;
            /** Derivation Kind */
            derivation_kind: string;
        };
        /** LiveStateRead */
        LiveStateRead: {
            /** Finished Goods Lots */
            finished_goods_lots: components["schemas"]["RecallFinishedGoodsLotLiveRead"][];
            /** Storage */
            storage: components["schemas"]["RecallLocationBalanceRead"][];
            /** Dispatches */
            dispatches: components["schemas"]["RecallDispatchLineRead"][];
        };
        /** LocationBulkChildrenCreate */
        LocationBulkChildrenCreate: {
            /** Location Type Code */
            location_type_code: string;
            /** Code Prefix */
            code_prefix: string;
            /** Start */
            start: number;
            /** End */
            end: number;
            /** Pad Width */
            pad_width: number;
            /** Name Template */
            name_template?: string | null;
        };
        /** LocationCreate */
        LocationCreate: {
            /** Location Type Code */
            location_type_code: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
            /** Parent Location Id */
            parent_location_id?: string | null;
            /** Greenhouse Classification */
            greenhouse_classification?: string | null;
            /** Occupiable */
            occupiable?: boolean | null;
        };
        /** LocationInventoryRead */
        LocationInventoryRead: {
            /**
             * Location Id
             * Format: uuid
             */
            location_id: string;
            /** Lots */
            lots: components["schemas"]["LotBalanceRead"][];
        };
        /** LocationPathEntry */
        LocationPathEntry: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
        };
        /** LocationPathRead */
        LocationPathRead: {
            /**
             * Location Id
             * Format: uuid
             */
            location_id: string;
            /** Path */
            path: components["schemas"]["LocationPathEntry"][];
            /** Path String */
            path_string: string;
        };
        /** LocationRead */
        LocationRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /**
             * Farm Id
             * Format: uuid
             */
            farm_id: string;
            /** Parent Location Id */
            parent_location_id: string | null;
            /**
             * Location Type Id
             * Format: uuid
             */
            location_type_id: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
            /** Status */
            status: string;
            /** Greenhouse Classification */
            greenhouse_classification: string | null;
            /** Occupiable */
            occupiable: boolean;
        };
        /** LocationTreeNode */
        LocationTreeNode: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
            /**
             * Location Type Id
             * Format: uuid
             */
            location_type_id: string;
            /** Status */
            status: string;
            /** Occupiable */
            occupiable: boolean;
            /**
             * Children
             * @default []
             */
            children: components["schemas"]["LocationTreeNode"][];
        };
        /** LotBalanceRead */
        LotBalanceRead: {
            /**
             * Finished Goods Lot Id
             * Format: uuid
             */
            finished_goods_lot_id: string;
            /** Finished Goods Lot Code */
            finished_goods_lot_code: string;
            /** Weight Kg */
            weight_kg: string;
            /** Package Count */
            package_count: number;
        };
        /** MembershipCreate */
        MembershipCreate: {
            /**
             * User Id
             * Format: uuid
             */
            user_id: string;
            /** Role Code */
            role_code: string;
        };
        /** MembershipRead */
        MembershipRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /**
             * User Id
             * Format: uuid
             */
            user_id: string;
            /** Status */
            status: string;
            /** Role Code */
            role_code: string | null;
        };
        /** MovementCreate */
        MovementCreate: {
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            occupant: components["schemas"]["OccupantRef"];
            destination?: components["schemas"]["TargetRef"] | null;
            /** Reason */
            reason?: string | null;
        };
        /** MovementRead */
        MovementRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /**
             * Farm Id
             * Format: uuid
             */
            farm_id: string;
            occupant: components["schemas"]["OccupantRef"];
            source: components["schemas"]["TargetRef"] | null;
            destination: components["schemas"]["TargetRef"] | null;
            /** Command Type */
            command_type: string;
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /**
             * Recorded Time
             * Format: date-time
             */
            recorded_time: string;
            /** Actor User Id */
            actor_user_id: string | null;
            /** Reason */
            reason: string | null;
        };
        /** ObservationDefinitionCreate */
        ObservationDefinitionCreate: {
            /** Code */
            code: string;
            /** Name */
            name: string;
            /** Description */
            description?: string | null;
            /** Value Type */
            value_type: string;
            /** Unit */
            unit?: string | null;
            /** Target Scope */
            target_scope: string;
            /** Min Value */
            min_value?: number | string | null;
            /** Max Value */
            max_value?: number | string | null;
        };
        /** ObservationDefinitionRead */
        ObservationDefinitionRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
            /** Description */
            description: string | null;
            /** Value Type */
            value_type: string;
            /** Unit */
            unit: string | null;
            /** Target Scope */
            target_scope: string;
            /** Min Value */
            min_value: string | null;
            /** Max Value */
            max_value: string | null;
            /** Status */
            status: string;
            /**
             * Created By User Id
             * Format: uuid
             */
            created_by_user_id: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
        };
        /** ObservationDefinitionSummary */
        ObservationDefinitionSummary: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
            /** Value Type */
            value_type: string;
            /** Unit */
            unit: string | null;
        };
        /** ObservationEventCreate */
        ObservationEventCreate: {
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /** Note */
            note?: string | null;
            /** Values */
            values?: components["schemas"]["ObservationValueIn"][];
            /** Germination Checks */
            germination_checks?: components["schemas"]["GerminationCheckIn"][];
        };
        /** ObservationEventRead */
        ObservationEventRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /**
             * Farm Id
             * Format: uuid
             */
            farm_id: string;
            /**
             * Batch Id
             * Format: uuid
             */
            batch_id: string;
            /** Batch Code */
            batch_code: string;
            /**
             * Workflow Version Id
             * Format: uuid
             */
            workflow_version_id: string;
            stage: components["schemas"]["StageSummary"];
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /**
             * Recorded Time
             * Format: date-time
             */
            recorded_time: string;
            /**
             * Actor User Id
             * Format: uuid
             */
            actor_user_id: string;
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            /** Note */
            note: string | null;
            /** Values */
            values: components["schemas"]["ObservationValueRead"][];
            /** Germination Checks */
            germination_checks: components["schemas"]["GerminationCheckRead"][];
        };
        /** ObservationValueIn */
        ObservationValueIn: {
            /**
             * Observation Definition Id
             * Format: uuid
             */
            observation_definition_id: string;
            /** Batch Carrier Assignment Id */
            batch_carrier_assignment_id?: string | null;
            /** Value Integer */
            value_integer?: number | null;
            /** Value Decimal */
            value_decimal?: number | string | null;
            /** Value Boolean */
            value_boolean?: boolean | null;
            /** Value Text */
            value_text?: string | null;
            /** Note */
            note?: string | null;
        };
        /** ObservationValueRead */
        ObservationValueRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            definition: components["schemas"]["ObservationDefinitionSummary"];
            carrier: components["schemas"]["CarrierSummary"] | null;
            /** Batch Carrier Assignment Id */
            batch_carrier_assignment_id: string | null;
            /** Value Integer */
            value_integer: number | null;
            /** Value Decimal */
            value_decimal: string | null;
            /** Value Boolean */
            value_boolean: boolean | null;
            /** Value Text */
            value_text: string | null;
            /** Note */
            note: string | null;
        };
        /** OccupancyRead */
        OccupancyRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /**
             * Farm Id
             * Format: uuid
             */
            farm_id: string;
            occupant: components["schemas"]["OccupantRef"];
            target: components["schemas"]["TargetRef"];
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /** End Time */
            end_time: string | null;
            /**
             * Opened By Movement Id
             * Format: uuid
             */
            opened_by_movement_id: string;
            /** Closed By Movement Id */
            closed_by_movement_id: string | null;
            /** Actor User Id */
            actor_user_id: string | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
        };
        /** OccupantRef */
        OccupantRef: {
            /**
             * Kind
             * @enum {string}
             */
            kind: "asset" | "carrier";
            /**
             * Id
             * Format: uuid
             */
            id: string;
        };
        /** PackingEventCreate */
        PackingEventCreate: {
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /** Finished Goods Lot Code */
            finished_goods_lot_code: string;
            /** Package Count */
            package_count: number;
            /** Packed Output Weight Kg */
            packed_output_weight_kg: number | string;
            /** Process Loss Weight Kg */
            process_loss_weight_kg: number | string;
            /** Rejected Weight Kg */
            rejected_weight_kg: number | string;
            /** Note */
            note?: string | null;
            /** Input Lines */
            input_lines: components["schemas"]["PackingInputLineIn"][];
        };
        /** PackingInputLineIn */
        PackingInputLineIn: {
            /**
             * Harvested Produce Lot Id
             * Format: uuid
             */
            harvested_produce_lot_id: string;
            /** Consumed Weight Kg */
            consumed_weight_kg: number | string;
            /** Consumed Whole Unit Count */
            consumed_whole_unit_count?: number | null;
            /** Note */
            note?: string | null;
        };
        /** PathEntry */
        PathEntry: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
        };
        /** ProduceLotBalanceRead */
        ProduceLotBalanceRead: {
            /**
             * Produce Lot Id
             * Format: uuid
             */
            produce_lot_id: string;
            /** Produce Lot Code */
            produce_lot_code: string;
            /** Received Weight Kg */
            received_weight_kg: string;
            /** Available Weight Kg */
            available_weight_kg: string;
            /** Received Whole Unit Count */
            received_whole_unit_count: number | null;
            /** Available Whole Unit Count */
            available_whole_unit_count: number | null;
            /** Entry Count */
            entry_count: number;
            /**
             * Last Effective Time
             * Format: date-time
             */
            last_effective_time: string;
        };
        /** ProduceLotLedgerEntryRead */
        ProduceLotLedgerEntryRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Entry Kind */
            entry_kind: string;
            /**
             * Produce Lot Id
             * Format: uuid
             */
            produce_lot_id: string;
            /** Produce Lot Code */
            produce_lot_code: string;
            /** Harvest Event Id */
            harvest_event_id: string | null;
            /** Packing Event Id */
            packing_event_id: string | null;
            /**
             * Actor User Id
             * Format: uuid
             */
            actor_user_id: string;
            /** Weight Delta Kg */
            weight_delta_kg: string;
            /** Whole Unit Count Delta */
            whole_unit_count_delta: number | null;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /**
             * Recorded Time
             * Format: date-time
             */
            recorded_time: string;
            /** Note */
            note: string | null;
        };
        /** ProductionSystemCreate */
        ProductionSystemCreate: {
            /** Code */
            code: string;
            /** Name */
            name: string;
            /** Description */
            description?: string | null;
        };
        /** ProductionSystemRead */
        ProductionSystemRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
            /** Description */
            description: string | null;
            /** Status */
            status: string;
        };
        /** ProductionSystemSummary */
        ProductionSystemSummary: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
        };
        /** QualityHoldCreate */
        QualityHoldCreate: {
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /** Source Observation Event Id */
            source_observation_event_id?: string | null;
            /** Reason Code */
            reason_code: string;
            /** Reason Text */
            reason_text: string;
        };
        /** QualityHoldReleaseCreate */
        QualityHoldReleaseCreate: {
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /** Release Reason */
            release_reason: string;
        };
        /** QualityHoldReleaseRead */
        QualityHoldReleaseRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Quality Hold Id
             * Format: uuid
             */
            quality_hold_id: string;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /**
             * Recorded Time
             * Format: date-time
             */
            recorded_time: string;
            /**
             * Actor User Id
             * Format: uuid
             */
            actor_user_id: string;
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            /** Release Reason */
            release_reason: string;
        };
        /** RecallCaseClose */
        RecallCaseClose: {
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /** Close Reason */
            close_reason: string;
        };
        /** RecallCaseClosureRead */
        RecallCaseClosureRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /**
             * Recorded Time
             * Format: date-time
             */
            recorded_time: string;
            /**
             * Actor User Id
             * Format: uuid
             */
            actor_user_id: string;
            /** Close Reason */
            close_reason: string;
        };
        /** RecallCaseCreate */
        RecallCaseCreate: {
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /** Code */
            code: string;
            /** Crop Batch Id */
            crop_batch_id?: string | null;
            /** Harvested Produce Lot Id */
            harvested_produce_lot_id?: string | null;
            /** Finished Goods Lot Id */
            finished_goods_lot_id?: string | null;
            /** Reason Code */
            reason_code: string;
            /** Reason Text */
            reason_text: string;
        };
        /** RecallCaseDetailRead */
        RecallCaseDetailRead: {
            /**
             * Recall Case Id
             * Format: uuid
             */
            recall_case_id: string;
            /** Code */
            code: string;
            /** Crop Batch Id */
            crop_batch_id: string | null;
            /** Harvested Produce Lot Id */
            harvested_produce_lot_id: string | null;
            /** Finished Goods Lot Id */
            finished_goods_lot_id: string | null;
            /** Reason Code */
            reason_code: string;
            /** Reason Text */
            reason_text: string;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /**
             * Recorded Time
             * Format: date-time
             */
            recorded_time: string;
            /**
             * Actor User Id
             * Format: uuid
             */
            actor_user_id: string;
            /** Is Open */
            is_open: boolean;
            closure: components["schemas"]["RecallCaseClosureRead"] | null;
            frozen_scope: components["schemas"]["FrozenScopeRead"];
            live_state: components["schemas"]["LiveStateRead"];
        };
        /** RecallCaseSummaryRead */
        RecallCaseSummaryRead: {
            /**
             * Recall Case Id
             * Format: uuid
             */
            recall_case_id: string;
            /** Code */
            code: string;
            /** Crop Batch Id */
            crop_batch_id: string | null;
            /** Harvested Produce Lot Id */
            harvested_produce_lot_id: string | null;
            /** Finished Goods Lot Id */
            finished_goods_lot_id: string | null;
            /** Reason Code */
            reason_code: string;
            /** Reason Text */
            reason_text: string;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /**
             * Recorded Time
             * Format: date-time
             */
            recorded_time: string;
            /**
             * Actor User Id
             * Format: uuid
             */
            actor_user_id: string;
            /** Is Open */
            is_open: boolean;
        };
        /** RecallDispatchLineRead */
        RecallDispatchLineRead: {
            /**
             * Dispatch Event Id
             * Format: uuid
             */
            dispatch_event_id: string;
            /** Dispatch Event Code */
            dispatch_event_code: string;
            /**
             * Dispatch Line Id
             * Format: uuid
             */
            dispatch_line_id: string;
            /**
             * Finished Goods Lot Id
             * Format: uuid
             */
            finished_goods_lot_id: string;
            /** Dispatched Weight Kg */
            dispatched_weight_kg: string;
            /** Dispatched Package Count */
            dispatched_package_count: number;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /**
             * Recorded Time
             * Format: date-time
             */
            recorded_time: string;
        };
        /** RecallFinishedGoodsLotLiveRead */
        RecallFinishedGoodsLotLiveRead: {
            /**
             * Finished Goods Lot Id
             * Format: uuid
             */
            finished_goods_lot_id: string;
            /** Code */
            code: string;
            /**
             * Packing Event Id
             * Format: uuid
             */
            packing_event_id: string;
            /** Net Packed Weight Kg */
            net_packed_weight_kg: string;
            /** Package Count */
            package_count: number;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /** Available Weight Kg */
            available_weight_kg: string;
            /** Available Package Count */
            available_package_count: number;
            /** Placed Weight Kg */
            placed_weight_kg: string;
            /** Placed Package Count */
            placed_package_count: number;
            /** Unplaced Weight Kg */
            unplaced_weight_kg: string;
            /** Unplaced Package Count */
            unplaced_package_count: number;
        };
        /** RecallLocationBalanceRead */
        RecallLocationBalanceRead: {
            /**
             * Finished Goods Lot Id
             * Format: uuid
             */
            finished_goods_lot_id: string;
            /**
             * Location Id
             * Format: uuid
             */
            location_id: string;
            /** Weight Kg */
            weight_kg: string;
            /** Package Count */
            package_count: number;
        };
        /** ResolvedLocationRead */
        ResolvedLocationRead: {
            occupant: components["schemas"]["OccupantRef"];
            direct_target: components["schemas"]["TargetRef"] | null;
            /** Position Path */
            position_path: components["schemas"]["PathEntry"][] | null;
            containing_asset: components["schemas"]["ContainingAssetRef"] | null;
            /** Fixed Location Path */
            fixed_location_path: components["schemas"]["PathEntry"][] | null;
            /** Path String */
            path_string: string | null;
            /** Unresolved Reason */
            unresolved_reason: string | null;
        };
        /** SeedLotCreate */
        SeedLotCreate: {
            /**
             * Crop Id
             * Format: uuid
             */
            crop_id: string;
            /**
             * Variety Id
             * Format: uuid
             */
            variety_id: string;
            /** Code */
            code: string;
            /** Supplier Name */
            supplier_name?: string | null;
            /** Supplier Lot Reference */
            supplier_lot_reference?: string | null;
            /** Received Date */
            received_date?: string | null;
            /** Expiry Date */
            expiry_date?: string | null;
        };
        /** SeedLotRead */
        SeedLotRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /**
             * Farm Id
             * Format: uuid
             */
            farm_id: string;
            crop: components["schemas"]["CropSummary"];
            variety: components["schemas"]["VarietySummary"];
            /** Code */
            code: string;
            /** Supplier Name */
            supplier_name: string | null;
            /** Supplier Lot Reference */
            supplier_lot_reference: string | null;
            /** Received Date */
            received_date: string | null;
            /** Expiry Date */
            expiry_date: string | null;
            /** Status */
            status: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
        };
        /** SeedLotSummary */
        SeedLotSummary: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Code */
            code: string;
            /** Supplier Lot Reference */
            supplier_lot_reference: string | null;
            crop: components["schemas"]["CropSummary"];
            variety: components["schemas"]["VarietySummary"];
        };
        /** SeedOrigin */
        SeedOrigin: {
            /**
             * Seed Lot Id
             * Format: uuid
             */
            seed_lot_id: string;
            /** Seed Lot Code */
            seed_lot_code: string;
            /**
             * Sowing Event Id
             * Format: uuid
             */
            sowing_event_id: string;
            /**
             * Sowing Event Line Id
             * Format: uuid
             */
            sowing_event_line_id: string;
            /**
             * Batch Carrier Assignment Id
             * Format: uuid
             */
            batch_carrier_assignment_id: string;
            /**
             * Carrier Id
             * Format: uuid
             */
            carrier_id: string;
            /**
             * Originating Batch Id
             * Format: uuid
             */
            originating_batch_id: string;
        };
        /** SowingEventCreate */
        SowingEventCreate: {
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /** Note */
            note?: string | null;
            /** Lines */
            lines: components["schemas"]["SowingEventLineIn"][];
        };
        /** SowingEventLineIn */
        SowingEventLineIn: {
            /**
             * Carrier Id
             * Format: uuid
             */
            carrier_id: string;
            /**
             * Seed Lot Id
             * Format: uuid
             */
            seed_lot_id: string;
            /** Sown Site Count */
            sown_site_count: number;
            /** Seed Count */
            seed_count: number;
            /** Line Note */
            line_note?: string | null;
        };
        /** SowingEventLineRead */
        SowingEventLineRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Batch Carrier Assignment Id
             * Format: uuid
             */
            batch_carrier_assignment_id: string;
            carrier: components["schemas"]["CarrierSummary"];
            seed_lot: components["schemas"]["SeedLotSummary"];
            /** Sown Site Count */
            sown_site_count: number;
            /** Seed Count */
            seed_count: number;
            /** Line Note */
            line_note: string | null;
        };
        /** SowingEventRead */
        SowingEventRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /**
             * Farm Id
             * Format: uuid
             */
            farm_id: string;
            /**
             * Batch Id
             * Format: uuid
             */
            batch_id: string;
            /** Batch Code */
            batch_code: string;
            /**
             * Workflow Version Id
             * Format: uuid
             */
            workflow_version_id: string;
            stage: components["schemas"]["StageSummary"];
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /**
             * Recorded Time
             * Format: date-time
             */
            recorded_time: string;
            /**
             * Actor User Id
             * Format: uuid
             */
            actor_user_id: string;
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            /** Note */
            note: string | null;
            /** Lines */
            lines: components["schemas"]["SowingEventLineRead"][];
        };
        /** SplitOutputIn */
        SplitOutputIn: {
            /** Output Batch Code */
            output_batch_code: string;
            /** Source Assignment Ids */
            source_assignment_ids: string[];
        };
        /** StageSummary */
        StageSummary: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
            /** Is Terminal */
            is_terminal: boolean;
        };
        /** StorageMovementRead */
        StorageMovementRead: {
            /**
             * Movement Id
             * Format: uuid
             */
            movement_id: string;
            /**
             * Finished Goods Lot Id
             * Format: uuid
             */
            finished_goods_lot_id: string;
            /** Movement Kind */
            movement_kind: string;
            /** Source Location Id */
            source_location_id: string | null;
            /** Destination Location Id */
            destination_location_id: string | null;
            /** Moved Weight Kg */
            moved_weight_kg: string;
            /** Moved Package Count */
            moved_package_count: number;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /**
             * Recorded Time
             * Format: date-time
             */
            recorded_time: string;
        };
        /** TargetOccupantRead */
        TargetOccupantRead: {
            target: components["schemas"]["TargetRef"];
            active_occupancy: components["schemas"]["OccupancyRead"] | null;
        };
        /** TargetRef */
        TargetRef: {
            /**
             * Kind
             * @enum {string}
             */
            kind: "location" | "asset_position";
            /**
             * Id
             * Format: uuid
             */
            id: string;
        };
        /** TenantCreate */
        TenantCreate: {
            /** Code */
            code: string;
            /** Name */
            name: string;
        };
        /** TenantRead */
        TenantRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
            /** Status */
            status: string;
        };
        /** TransplantAllocationIn */
        TransplantAllocationIn: {
            /**
             * Source Assignment Id
             * Format: uuid
             */
            source_assignment_id: string;
            /**
             * Destination Carrier Id
             * Format: uuid
             */
            destination_carrier_id: string;
            /** Allocated Plant Count */
            allocated_plant_count: number;
        };
        /** TransplantAllocationRead */
        TransplantAllocationRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            source_carrier: components["schemas"]["CarrierSummary"];
            destination_carrier: components["schemas"]["CarrierSummary"];
            /** Allocated Plant Count */
            allocated_plant_count: number;
        };
        /** TransplantDestinationLineIn */
        TransplantDestinationLineIn: {
            /**
             * Destination Carrier Id
             * Format: uuid
             */
            destination_carrier_id: string;
            /** Assigned Plant Count */
            assigned_plant_count: number;
            /** Note */
            note?: string | null;
        };
        /** TransplantDestinationLineRead */
        TransplantDestinationLineRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Destination Batch Carrier Assignment Id
             * Format: uuid
             */
            destination_batch_carrier_assignment_id: string;
            carrier: components["schemas"]["CarrierSummary"];
            /** Assigned Plant Count */
            assigned_plant_count: number;
            /** Allocated Plant Count */
            allocated_plant_count: number;
            /** Note */
            note: string | null;
        };
        /** TransplantEventCreate */
        TransplantEventCreate: {
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /** Note */
            note?: string | null;
            /** Source Lines */
            source_lines: components["schemas"]["TransplantSourceLineIn"][];
            /** Destination Lines */
            destination_lines: components["schemas"]["TransplantDestinationLineIn"][];
            /** Allocations */
            allocations: components["schemas"]["TransplantAllocationIn"][];
        };
        /** TransplantEventRead */
        TransplantEventRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /**
             * Farm Id
             * Format: uuid
             */
            farm_id: string;
            /**
             * Batch Id
             * Format: uuid
             */
            batch_id: string;
            /** Batch Code */
            batch_code: string;
            /**
             * Workflow Version Id
             * Format: uuid
             */
            workflow_version_id: string;
            stage: components["schemas"]["StageSummary"];
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /**
             * Recorded Time
             * Format: date-time
             */
            recorded_time: string;
            /**
             * Actor User Id
             * Format: uuid
             */
            actor_user_id: string;
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            /** Note */
            note: string | null;
            /** Source Lines */
            source_lines: components["schemas"]["TransplantSourceLineRead"][];
            /** Destination Lines */
            destination_lines: components["schemas"]["TransplantDestinationLineRead"][];
            /** Allocations */
            allocations: components["schemas"]["TransplantAllocationRead"][];
            /** Total Source Plant Count */
            total_source_plant_count: number;
            /** Total Destination Plant Count */
            total_destination_plant_count: number;
            /** Total Discarded Plant Count */
            total_discarded_plant_count: number;
        };
        /** TransplantSourceLineIn */
        TransplantSourceLineIn: {
            /**
             * Source Assignment Id
             * Format: uuid
             */
            source_assignment_id: string;
            /** Source Plant Count */
            source_plant_count: number;
            /** Discarded Plant Count */
            discarded_plant_count: number;
            /** Note */
            note?: string | null;
        };
        /** TransplantSourceLineRead */
        TransplantSourceLineRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Source Batch Carrier Assignment Id
             * Format: uuid
             */
            source_batch_carrier_assignment_id: string;
            carrier: components["schemas"]["CarrierSummary"];
            seed_lot: components["schemas"]["SeedLotSummary"];
            /**
             * Sowing Event Id
             * Format: uuid
             */
            sowing_event_id: string;
            /** Source Plant Count */
            source_plant_count: number;
            /** Discarded Plant Count */
            discarded_plant_count: number;
            /** Allocated Plant Count */
            allocated_plant_count: number;
            /** Note */
            note: string | null;
        };
        /** UserCreate */
        UserCreate: {
            /** Oidc Issuer */
            oidc_issuer: string;
            /** Oidc Subject */
            oidc_subject: string;
            /** Email */
            email: string;
            /** Display Name */
            display_name: string;
        };
        /** UserRead */
        UserRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Oidc Issuer */
            oidc_issuer: string;
            /** Oidc Subject */
            oidc_subject: string;
            /** Email */
            email: string;
            /** Display Name */
            display_name: string;
            /** Status */
            status: string;
        };
        /** ValidationError */
        ValidationError: {
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
            /** Input */
            input?: unknown;
            /** Context */
            ctx?: Record<string, never>;
        };
        /** VarietyCreate */
        VarietyCreate: {
            /** Code */
            code: string;
            /** Name */
            name: string;
            /** Supplier Reference */
            supplier_reference?: string | null;
        };
        /** VarietyRead */
        VarietyRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /**
             * Crop Id
             * Format: uuid
             */
            crop_id: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
            /** Supplier Reference */
            supplier_reference: string | null;
            /** Status */
            status: string;
        };
        /** VarietySummary */
        VarietySummary: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
        };
        /** WorkflowCreate */
        WorkflowCreate: {
            /**
             * Crop Id
             * Format: uuid
             */
            crop_id: string;
            /** Variety Id */
            variety_id?: string | null;
            /**
             * Production System Id
             * Format: uuid
             */
            production_system_id: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
        };
        /** WorkflowRead */
        WorkflowRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /**
             * Crop Id
             * Format: uuid
             */
            crop_id: string;
            /** Variety Id */
            variety_id: string | null;
            /**
             * Production System Id
             * Format: uuid
             */
            production_system_id: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
            /** Status */
            status: string;
        };
        /** WorkflowStageCreate */
        WorkflowStageCreate: {
            /** Code */
            code: string;
            /** Name */
            name: string;
            /** Display Order */
            display_order: number;
            /** Stage Category */
            stage_category: string;
            /** Expected Duration Minutes */
            expected_duration_minutes?: number | null;
            /** Permitted Location Type Code */
            permitted_location_type_code?: string | null;
            /** Required Carrier Type Code */
            required_carrier_type_code?: string | null;
            /**
             * Is Start
             * @default false
             */
            is_start: boolean;
            /**
             * Is Terminal
             * @default false
             */
            is_terminal: boolean;
        };
        /** WorkflowStageRead */
        WorkflowStageRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /**
             * Workflow Version Id
             * Format: uuid
             */
            workflow_version_id: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
            /** Display Order */
            display_order: number;
            /** Stage Category */
            stage_category: string;
            /** Expected Duration Minutes */
            expected_duration_minutes: number | null;
            /** Permitted Location Type Id */
            permitted_location_type_id: string | null;
            /** Required Carrier Type Id */
            required_carrier_type_id: string | null;
            /** Is Start */
            is_start: boolean;
            /** Is Terminal */
            is_terminal: boolean;
        };
        /** WorkflowSummary */
        WorkflowSummary: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
        };
        /** WorkflowTransitionCreate */
        WorkflowTransitionCreate: {
            /**
             * From Stage Id
             * Format: uuid
             */
            from_stage_id: string;
            /**
             * To Stage Id
             * Format: uuid
             */
            to_stage_id: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
        };
        /** WorkflowTransitionRead */
        WorkflowTransitionRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /**
             * Workflow Version Id
             * Format: uuid
             */
            workflow_version_id: string;
            /**
             * From Stage Id
             * Format: uuid
             */
            from_stage_id: string;
            /**
             * To Stage Id
             * Format: uuid
             */
            to_stage_id: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
        };
        /** WorkflowVersionDetailRead */
        WorkflowVersionDetailRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /**
             * Workflow Id
             * Format: uuid
             */
            workflow_id: string;
            /** Version Number */
            version_number: number;
            /** State */
            state: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Published At */
            published_at: string | null;
            /** Retired At */
            retired_at: string | null;
            /** Stages */
            stages: components["schemas"]["WorkflowStageRead"][];
            /** Transitions */
            transitions: components["schemas"]["WorkflowTransitionRead"][];
        };
        /** WorkflowVersionRead */
        WorkflowVersionRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /**
             * Workflow Id
             * Format: uuid
             */
            workflow_id: string;
            /** Version Number */
            version_number: number;
            /** State */
            state: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Published At */
            published_at: string | null;
            /** Retired At */
            retired_at: string | null;
        };
        /** DispatchLineRead */
        app__schemas__dispatch__DispatchLineRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Finished Goods Lot Id
             * Format: uuid
             */
            finished_goods_lot_id: string;
            /** Finished Goods Lot Code */
            finished_goods_lot_code: string;
            /** Dispatched Weight Kg */
            dispatched_weight_kg: string;
            /** Dispatched Package Count */
            dispatched_package_count: number;
            /**
             * Ledger Entry Id
             * Format: uuid
             */
            ledger_entry_id: string;
        };
        /** LocationBalanceRead */
        app__schemas__finished_goods_storage__LocationBalanceRead: {
            /**
             * Location Id
             * Format: uuid
             */
            location_id: string;
            /** Weight Kg */
            weight_kg: string;
            /** Package Count */
            package_count: number;
        };
        /** HarvestEventRead */
        app__schemas__harvest__HarvestEventRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /**
             * Farm Id
             * Format: uuid
             */
            farm_id: string;
            /**
             * Batch Id
             * Format: uuid
             */
            batch_id: string;
            /** Batch Code */
            batch_code: string;
            workflow: components["schemas"]["WorkflowSummary"];
            /**
             * Workflow Version Id
             * Format: uuid
             */
            workflow_version_id: string;
            crop: components["schemas"]["CropSummary"];
            variety: components["schemas"]["VarietySummary"] | null;
            stage: components["schemas"]["StageSummary"];
            /**
             * Produce Lot Id
             * Format: uuid
             */
            produce_lot_id: string;
            /** Produce Lot Code */
            produce_lot_code: string;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /**
             * Recorded Time
             * Format: date-time
             */
            recorded_time: string;
            /**
             * Actor User Id
             * Format: uuid
             */
            actor_user_id: string;
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            /** Note */
            note: string | null;
            /** Source Lines */
            source_lines: components["schemas"]["HarvestSourceLineRead"][];
            /** Total Harvested Weight Kg */
            total_harvested_weight_kg: string;
            /** Total Whole Unit Count */
            total_whole_unit_count: number | null;
        };
        /** HarvestedProduceLotRead */
        app__schemas__harvest__HarvestedProduceLotRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /**
             * Farm Id
             * Format: uuid
             */
            farm_id: string;
            /** Code */
            code: string;
            /**
             * Harvest Event Id
             * Format: uuid
             */
            harvest_event_id: string;
            /**
             * Batch Id
             * Format: uuid
             */
            batch_id: string;
            /** Batch Code */
            batch_code: string;
            workflow: components["schemas"]["WorkflowSummary"];
            /**
             * Workflow Version Id
             * Format: uuid
             */
            workflow_version_id: string;
            crop: components["schemas"]["CropSummary"];
            variety: components["schemas"]["VarietySummary"] | null;
            /** Total Harvested Weight Kg */
            total_harvested_weight_kg: string;
            /** Total Whole Unit Count */
            total_whole_unit_count: number | null;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /**
             * Recorded At
             * Format: date-time
             */
            recorded_at: string;
            /** Source Lines */
            source_lines: components["schemas"]["HarvestSourceLineRead"][];
        };
        /** FinishedGoodsLotRead */
        app__schemas__packing__FinishedGoodsLotRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /**
             * Farm Id
             * Format: uuid
             */
            farm_id: string;
            /** Code */
            code: string;
            /**
             * Packing Event Id
             * Format: uuid
             */
            packing_event_id: string;
            crop: components["schemas"]["CropSummary"];
            variety: components["schemas"]["VarietySummary"] | null;
            /** Net Packed Weight Kg */
            net_packed_weight_kg: string;
            /** Package Count */
            package_count: number;
            /** Source Produce Lot Ids */
            source_produce_lot_ids: string[];
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /**
             * Recorded Time
             * Format: date-time
             */
            recorded_time: string;
        };
        /** PackingEventRead */
        app__schemas__packing__PackingEventRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /**
             * Farm Id
             * Format: uuid
             */
            farm_id: string;
            crop: components["schemas"]["CropSummary"];
            variety: components["schemas"]["VarietySummary"] | null;
            finished_goods_lot: components["schemas"]["FinishedGoodsLotSummary"];
            /** Input Lines */
            input_lines: components["schemas"]["app__schemas__packing__PackingInputLineRead"][];
            /** Total Input Weight Kg */
            total_input_weight_kg: string;
            /** Packed Output Weight Kg */
            packed_output_weight_kg: string;
            /** Process Loss Weight Kg */
            process_loss_weight_kg: string;
            /** Rejected Weight Kg */
            rejected_weight_kg: string;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /**
             * Recorded Time
             * Format: date-time
             */
            recorded_time: string;
            /**
             * Actor User Id
             * Format: uuid
             */
            actor_user_id: string;
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            /** Note */
            note: string | null;
        };
        /** PackingInputLineRead */
        app__schemas__packing__PackingInputLineRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Harvested Produce Lot Id
             * Format: uuid
             */
            harvested_produce_lot_id: string;
            /** Produce Lot Code */
            produce_lot_code: string;
            /**
             * Harvest Event Id
             * Format: uuid
             */
            harvest_event_id: string;
            /** Consumed Weight Kg */
            consumed_weight_kg: string;
            /** Consumed Whole Unit Count */
            consumed_whole_unit_count: number | null;
            /**
             * Ledger Entry Id
             * Format: uuid
             */
            ledger_entry_id: string;
            /** Note */
            note: string | null;
            /**
             * Recorded Time
             * Format: date-time
             */
            recorded_time: string;
        };
        /** QualityHoldRead */
        app__schemas__quality_hold__QualityHoldRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /**
             * Farm Id
             * Format: uuid
             */
            farm_id: string;
            /**
             * Batch Id
             * Format: uuid
             */
            batch_id: string;
            stage: components["schemas"]["StageSummary"];
            /** Source Observation Event Id */
            source_observation_event_id: string | null;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /**
             * Recorded Time
             * Format: date-time
             */
            recorded_time: string;
            /**
             * Actor User Id
             * Format: uuid
             */
            actor_user_id: string;
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            /** Reason Code */
            reason_code: string;
            /** Reason Text */
            reason_text: string;
            /** Is Open */
            is_open: boolean;
            release: components["schemas"]["QualityHoldReleaseRead"] | null;
        };
        /** DispatchLineRead */
        app__schemas__traceability__DispatchLineRead: {
            /**
             * Dispatch Event Id
             * Format: uuid
             */
            dispatch_event_id: string;
            /** Dispatch Event Code */
            dispatch_event_code: string;
            /**
             * Dispatch Line Id
             * Format: uuid
             */
            dispatch_line_id: string;
            /**
             * Finished Goods Lot Id
             * Format: uuid
             */
            finished_goods_lot_id: string;
            /** Dispatched Weight Kg */
            dispatched_weight_kg: string;
            /** Dispatched Package Count */
            dispatched_package_count: number;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /**
             * Recorded Time
             * Format: date-time
             */
            recorded_time: string;
        };
        /** FinishedGoodsLotRead */
        app__schemas__traceability__FinishedGoodsLotRead: {
            /**
             * Finished Goods Lot Id
             * Format: uuid
             */
            finished_goods_lot_id: string;
            /** Code */
            code: string;
            /**
             * Packing Event Id
             * Format: uuid
             */
            packing_event_id: string;
            /** Net Packed Weight Kg */
            net_packed_weight_kg: string;
            /** Package Count */
            package_count: number;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /** Available Weight Kg */
            available_weight_kg: string;
            /** Available Package Count */
            available_package_count: number;
            /** Placed Weight Kg */
            placed_weight_kg: string;
            /** Placed Package Count */
            placed_package_count: number;
            /** Unplaced Weight Kg */
            unplaced_weight_kg: string;
            /** Unplaced Package Count */
            unplaced_package_count: number;
        };
        /** HarvestEventRead */
        app__schemas__traceability__HarvestEventRead: {
            /**
             * Harvest Event Id
             * Format: uuid
             */
            harvest_event_id: string;
            /**
             * Batch Id
             * Format: uuid
             */
            batch_id: string;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /**
             * Recorded Time
             * Format: date-time
             */
            recorded_time: string;
        };
        /** HarvestedProduceLotRead */
        app__schemas__traceability__HarvestedProduceLotRead: {
            /**
             * Harvested Produce Lot Id
             * Format: uuid
             */
            harvested_produce_lot_id: string;
            /** Code */
            code: string;
            /**
             * Harvest Event Id
             * Format: uuid
             */
            harvest_event_id: string;
            /**
             * Batch Id
             * Format: uuid
             */
            batch_id: string;
            /** Total Harvested Weight Kg */
            total_harvested_weight_kg: string;
            /** Total Whole Unit Count */
            total_whole_unit_count: number | null;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
        };
        /** LocationBalanceRead */
        app__schemas__traceability__LocationBalanceRead: {
            /**
             * Location Id
             * Format: uuid
             */
            location_id: string;
            /** Weight Kg */
            weight_kg: string;
            /** Package Count */
            package_count: number;
        };
        /** PackingEventRead */
        app__schemas__traceability__PackingEventRead: {
            /**
             * Packing Event Id
             * Format: uuid
             */
            packing_event_id: string;
            /** Total Input Weight Kg */
            total_input_weight_kg: string;
            /** Packed Output Weight Kg */
            packed_output_weight_kg: string;
            /** Process Loss Weight Kg */
            process_loss_weight_kg: string;
            /** Rejected Weight Kg */
            rejected_weight_kg: string;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /**
             * Recorded Time
             * Format: date-time
             */
            recorded_time: string;
        };
        /** PackingInputLineRead */
        app__schemas__traceability__PackingInputLineRead: {
            /**
             * Packing Input Line Id
             * Format: uuid
             */
            packing_input_line_id: string;
            /**
             * Packing Event Id
             * Format: uuid
             */
            packing_event_id: string;
            /**
             * Harvested Produce Lot Id
             * Format: uuid
             */
            harvested_produce_lot_id: string;
            /** Consumed Weight Kg */
            consumed_weight_kg: string;
            /** Consumed Whole Unit Count */
            consumed_whole_unit_count: number | null;
            /** Is Affected Source */
            is_affected_source?: boolean | null;
        };
        /** QualityHoldRead */
        app__schemas__traceability__QualityHoldRead: {
            /**
             * Quality Hold Id
             * Format: uuid
             */
            quality_hold_id: string;
            /**
             * Batch Id
             * Format: uuid
             */
            batch_id: string;
            /** Reason Code */
            reason_code: string;
            /** Reason Text */
            reason_text: string;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /** Is Open */
            is_open: boolean;
            /** Released Effective Time */
            released_effective_time?: string | null;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    get_health_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
        };
    };
    get_ready_ready_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
        };
    };
    create_membership_memberships_post: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MembershipCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MembershipRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_farms_farms_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FarmRead"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_farm_farms_post: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["FarmCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FarmRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_farm_farms__farm_id__get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FarmRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_location_farms__farm_id__locations_post: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LocationCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LocationRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    bulk_create_children_farms__farm_id__locations__parent_id__bulk_children_post: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                parent_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LocationBulkChildrenCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LocationRead"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_farm_tree_farms__farm_id__locations_tree_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LocationTreeNode"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_location_farms__farm_id__locations__location_id__get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                location_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LocationRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_children_farms__farm_id__locations__location_id__children_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                location_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LocationRead"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_path_farms__farm_id__locations__location_id__path_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                location_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LocationPathRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_location_occupant_farms__farm_id__locations__location_id__occupant_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                location_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TargetOccupantRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_assets_farms__farm_id__assets_get: {
        parameters: {
            query?: {
                asset_type?: string | null;
            };
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AssetRead"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    register_asset_farms__farm_id__assets_post: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AssetCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AssetRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_asset_farms__farm_id__assets__asset_id__get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                asset_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AssetRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    generate_positions_farms__farm_id__assets__asset_id__positions_generate_post: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                asset_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AssetPositionsGenerate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AssetPositionRead"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_positions_tree_farms__farm_id__assets__asset_id__positions_tree_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                asset_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AssetPositionTreeNode"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_asset_occupancy_farms__farm_id__assets__asset_id__occupancy_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                asset_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OccupancyRead"] | null;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_asset_movement_history_farms__farm_id__assets__asset_id__movement_history_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                asset_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MovementRead"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_asset_resolved_location_farms__farm_id__assets__asset_id__resolved_location_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                asset_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ResolvedLocationRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_position_occupant_farms__farm_id__assets__asset_id__positions__position_id__occupant_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                asset_id: string;
                position_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TargetOccupantRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_carriers_farms__farm_id__carriers_get: {
        parameters: {
            query?: {
                carrier_type?: string | null;
            };
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CarrierRead"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    register_carrier_farms__farm_id__carriers_post: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CarrierCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CarrierRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    bulk_register_carriers_farms__farm_id__carriers_bulk_post: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CarrierBulkCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CarrierRead"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_carrier_farms__farm_id__carriers__carrier_id__get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                carrier_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CarrierRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_carrier_occupancy_farms__farm_id__carriers__carrier_id__occupancy_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                carrier_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OccupancyRead"] | null;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_carrier_movement_history_farms__farm_id__carriers__carrier_id__movement_history_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                carrier_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MovementRead"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_carrier_resolved_location_farms__farm_id__carriers__carrier_id__resolved_location_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                carrier_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ResolvedLocationRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_movement_farms__farm_id__movements_post: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MovementCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MovementRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_crops_crops_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CropRead"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_crop_crops_post: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CropCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CropRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_crop_crops__crop_id__get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                crop_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CropRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_varieties_crops__crop_id__varieties_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                crop_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["VarietyRead"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_variety_crops__crop_id__varieties_post: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                crop_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["VarietyCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["VarietyRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_variety_crops__crop_id__varieties__variety_id__get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                crop_id: string;
                variety_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["VarietyRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_production_systems_production_systems_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProductionSystemRead"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_production_system_production_systems_post: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProductionSystemCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProductionSystemRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_production_system_production_systems__production_system_id__get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                production_system_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProductionSystemRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_workflows_workflows_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkflowRead"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_workflow_workflows_post: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["WorkflowCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkflowRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_draft_version_workflows__workflow_id__versions_post: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                workflow_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkflowVersionRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_workflow_version_workflows__workflow_id__versions__version_id__get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                workflow_id: string;
                version_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkflowVersionDetailRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    add_stage_workflows__workflow_id__versions__version_id__stages_post: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                workflow_id: string;
                version_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["WorkflowStageCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkflowStageRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    add_transition_workflows__workflow_id__versions__version_id__transitions_post: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                workflow_id: string;
                version_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["WorkflowTransitionCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkflowTransitionRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    publish_workflow_version_workflows__workflow_id__versions__version_id__publish_post: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                workflow_id: string;
                version_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkflowVersionRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_crop_batches_farms__farm_id__crop_batches_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CropBatchRead"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_crop_batch_farms__farm_id__crop_batches_post: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CropBatchCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CropBatchRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_crop_batch_farms__farm_id__crop_batches__batch_id__get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                batch_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CropBatchRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_stage_transition_farms__farm_id__crop_batches__batch_id__stage_transitions_post: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                batch_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["BatchStageTransitionCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BatchStageTransitionRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_current_stage_farms__farm_id__crop_batches__batch_id__current_stage_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                batch_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CurrentStageRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_stage_history_farms__farm_id__crop_batches__batch_id__stage_history_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                batch_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BatchStageRunRead"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_stage_transition_farms__farm_id__crop_batches__batch_id__stage_transitions__transition_id__get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                batch_id: string;
                transition_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BatchStageTransitionRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    split_crop_batch_farms__farm_id__crop_batches__batch_id__split_post: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                batch_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["BatchSplitCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BatchDerivationEventRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    merge_crop_batches_farms__farm_id__crop_batch_merges_post: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["BatchMergeCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BatchDerivationEventRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_batch_derivation_farms__farm_id__batch_derivations__derivation_event_id__get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                derivation_event_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BatchDerivationEventRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_crop_batch_lineage_farms__farm_id__crop_batches__batch_id__lineage_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                batch_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BatchLineageRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_seed_lots_farms__farm_id__seed_lots_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SeedLotRead"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    register_seed_lot_farms__farm_id__seed_lots_post: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SeedLotCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SeedLotRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_seed_lot_farms__farm_id__seed_lots__seed_lot_id__get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                seed_lot_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SeedLotRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_sowings_farms__farm_id__crop_batches__batch_id__sowings_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                batch_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SowingEventRead"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    sow_batch_farms__farm_id__crop_batches__batch_id__sowings_post: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                batch_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SowingEventCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SowingEventRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_sowing_farms__farm_id__crop_batches__batch_id__sowings__sowing_event_id__get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                batch_id: string;
                sowing_event_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SowingEventRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_batch_carriers_farms__farm_id__crop_batches__batch_id__carriers_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                batch_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BatchCarrierAssignmentRead"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_carrier_batch_assignment_farms__farm_id__carriers__carrier_id__batch_assignment_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                carrier_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BatchCarrierAssignmentRead"] | null;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_observation_definitions_observation_definitions_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ObservationDefinitionRead"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_observation_definition_observation_definitions_post: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ObservationDefinitionCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ObservationDefinitionRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_observation_definition_observation_definitions__definition_id__get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                definition_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ObservationDefinitionRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_observations_farms__farm_id__crop_batches__batch_id__observations_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                batch_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ObservationEventRead"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    record_observation_farms__farm_id__crop_batches__batch_id__observations_post: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                batch_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ObservationEventCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ObservationEventRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_observation_farms__farm_id__crop_batches__batch_id__observations__observation_event_id__get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                batch_id: string;
                observation_event_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ObservationEventRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_quality_holds_farms__farm_id__crop_batches__batch_id__quality_holds_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                batch_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["app__schemas__quality_hold__QualityHoldRead"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    place_quality_hold_farms__farm_id__crop_batches__batch_id__quality_holds_post: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                batch_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["QualityHoldCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["app__schemas__quality_hold__QualityHoldRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_quality_hold_farms__farm_id__crop_batches__batch_id__quality_holds__hold_id__get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                batch_id: string;
                hold_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["app__schemas__quality_hold__QualityHoldRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    release_quality_hold_farms__farm_id__crop_batches__batch_id__quality_holds__hold_id__release_post: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                batch_id: string;
                hold_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["QualityHoldReleaseCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["app__schemas__quality_hold__QualityHoldRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_transplants_farms__farm_id__crop_batches__batch_id__transplants_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                batch_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TransplantEventRead"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    record_transplant_farms__farm_id__crop_batches__batch_id__transplants_post: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                batch_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TransplantEventCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TransplantEventRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_transplant_farms__farm_id__crop_batches__batch_id__transplants__transplant_event_id__get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                batch_id: string;
                transplant_event_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TransplantEventRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_harvests_farms__farm_id__crop_batches__batch_id__harvests_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                batch_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["app__schemas__harvest__HarvestEventRead"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    record_harvest_farms__farm_id__crop_batches__batch_id__harvests_post: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                batch_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["HarvestEventCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["app__schemas__harvest__HarvestEventRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_harvest_farms__farm_id__crop_batches__batch_id__harvests__harvest_event_id__get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                batch_id: string;
                harvest_event_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["app__schemas__harvest__HarvestEventRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_harvested_produce_lots_farms__farm_id__harvested_produce_lots_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["app__schemas__harvest__HarvestedProduceLotRead"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_harvested_produce_lot_farms__farm_id__harvested_produce_lots__produce_lot_id__get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                produce_lot_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["app__schemas__harvest__HarvestedProduceLotRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_produce_lot_ledger_farms__farm_id__harvested_produce_lots__produce_lot_id__ledger_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                produce_lot_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProduceLotLedgerEntryRead"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_produce_lot_balance_farms__farm_id__harvested_produce_lots__produce_lot_id__balance_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                produce_lot_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProduceLotBalanceRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_packing_events_farms__farm_id__packing_events_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["app__schemas__packing__PackingEventRead"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    record_packing_farms__farm_id__packing_events_post: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PackingEventCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["app__schemas__packing__PackingEventRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_packing_event_farms__farm_id__packing_events__packing_event_id__get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                packing_event_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["app__schemas__packing__PackingEventRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_finished_goods_lots_farms__farm_id__finished_goods_lots_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["app__schemas__packing__FinishedGoodsLotRead"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_finished_goods_lot_farms__farm_id__finished_goods_lots__finished_goods_lot_id__get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                finished_goods_lot_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["app__schemas__packing__FinishedGoodsLotRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_finished_goods_ledger_farms__farm_id__finished_goods_lots__finished_goods_lot_id__ledger_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                finished_goods_lot_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FinishedGoodsLedgerEntryRead"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_finished_goods_balance_farms__farm_id__finished_goods_lots__finished_goods_lot_id__balance_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                finished_goods_lot_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FinishedGoodsBalanceRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_dispatch_events_farms__farm_id__dispatches_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DispatchEventRead"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    record_dispatch_farms__farm_id__dispatches_post: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DispatchEventCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DispatchEventRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_dispatch_event_farms__farm_id__dispatches__dispatch_event_id__get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                dispatch_event_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DispatchEventRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    record_movement_farms__farm_id__finished_goods_storage_movements_post: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["FinishedGoodsStorageMovementCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FinishedGoodsStorageMovementRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_storage_movements_farms__farm_id__finished_goods_lots__finished_goods_lot_id__storage_movements_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                finished_goods_lot_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FinishedGoodsStorageMovementRead"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_placement_farms__farm_id__finished_goods_lots__finished_goods_lot_id__placements_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                finished_goods_lot_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FinishedGoodsPlacementRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_location_inventory_farms__farm_id__locations__location_id__finished_goods_inventory_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                location_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LocationInventoryRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_finished_goods_lot_trace_farms__farm_id__traceability_finished_goods_lots__finished_goods_lot_id__get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                finished_goods_lot_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FinishedGoodsLotTraceRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_crop_batch_impact_farms__farm_id__traceability_crop_batches__crop_batch_id__impact_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                crop_batch_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CropBatchImpactRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_harvested_produce_lot_impact_farms__farm_id__traceability_harvested_produce_lots__produce_lot_id__impact_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                produce_lot_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HarvestedProduceLotImpactRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_recall_cases_farms__farm_id__recall_cases_get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RecallCaseSummaryRead"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    open_recall_case_farms__farm_id__recall_cases_post: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RecallCaseCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RecallCaseDetailRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_recall_case_farms__farm_id__recall_cases__recall_case_id__get: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                recall_case_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RecallCaseDetailRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    close_recall_case_farms__farm_id__recall_cases__recall_case_id__close_post: {
        parameters: {
            query?: never;
            header: {
                "X-Dev-Tenant-Id": string;
                "X-Dev-User-Id": string;
            };
            path: {
                farm_id: string;
                recall_case_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RecallCaseClose"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RecallCaseDetailRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    bootstrap_tenant_dev_bootstrap_tenants_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TenantCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TenantRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    bootstrap_user_dev_bootstrap_users_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UserCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UserRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    bootstrap_membership_dev_bootstrap_memberships_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["BootstrapMembershipCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MembershipRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    root__get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
        };
    };
}
