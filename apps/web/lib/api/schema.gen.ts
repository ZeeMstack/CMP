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
    "/auth/me": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Auth Me
         * @description Deliberately does not require X-CMP-Tenant-Id -- its whole purpose
         *     is letting a client discover which tenants it may select next.
         *     `require_authenticated_principal` has already proven the caller is a
         *     known, active CMP user (unknown/inactive identities never reach this
         *     body -- 403 before this point). Zero accessible memberships is a
         *     perfectly valid, successful response (`memberships: []`), not an
         *     error -- that's how a frontend knows to show "access not
         *     provisioned".
         */
        get: operations["get_auth_me_auth_me_get"];
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
    "/farms/{farm_id}/locations/{location_id}/occupants": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Location Occupants
         * @description DOMAIN-FARM-002.1: the truthful, complete-state counterpart to
         *     `get_location_occupant` -- returns every active occupancy, not just
         *     one, so a capacity>1 target is never under-reported.
         */
        get: operations["get_location_occupants_farms__farm_id__locations__location_id__occupants_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/locations/{location_id}/subtree-occupancy": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Location Subtree Occupancy
         * @description CMP-FE-002A: bounded-by-root occupancy for one location subtree
         *     (the given root plus all its descendants, never farm-wide). Returns
         *     aggregate occupiable/occupied counts per structural node plus only the
         *     currently occupied locations -- never resends the structural tree
         *     itself (already available from `.../locations/tree`), and never one
         *     row per empty location.
         */
        get: operations["get_location_subtree_occupancy_farms__farm_id__locations__location_id__subtree_occupancy_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/farm-setup/greenhouses": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Greenhouse Setup Overview */
        get: operations["get_greenhouse_setup_overview_farms__farm_id__farm_setup_greenhouses_get"];
        put?: never;
        /**
         * Create Greenhouse Setup
         * @description FARM-SETUP-001: creates a Greenhouse plus its full requested
         *     classification-specific physical structure in one atomic command.
         *
         *     FARM-SETUP-001.1: gated on BOTH `location.manage` AND `asset.manage`,
         *     stacked as two separate dependencies -- this command can register
         *     Nursery Assets (trolleys, seeding machines), so it must not rely on
         *     the incidental fact that every role currently holding `location.manage`
         *     also holds `asset.manage`. A hypothetical membership with only one of
         *     the two permissions must not be able to create Assets through this
         *     command.
         */
        post: operations["create_greenhouse_setup_farms__farm_id__farm_setup_greenhouses_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/farm-setup/greenhouses/{greenhouse_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Greenhouse Structure */
        get: operations["get_greenhouse_structure_farms__farm_id__farm_setup_greenhouses__greenhouse_id__get"];
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
    "/farms/{farm_id}/assets/{asset_id}/positions/{position_id}/occupants": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Position Occupants
         * @description DOMAIN-FARM-002.1: the truthful, complete-state counterpart to
         *     `get_position_occupant` -- returns every active occupancy, not just
         *     one, so a capacity>1 position is never under-reported.
         */
        get: operations["get_position_occupants_farms__farm_id__assets__asset_id__positions__position_id__occupants_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/carrier-types": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Carrier Types */
        get: operations["list_carrier_types_carrier_types_get"];
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
    "/carrier-specifications": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Carrier Specifications */
        get: operations["list_carrier_specifications_carrier_specifications_get"];
        put?: never;
        /** Create Carrier Specification */
        post: operations["create_carrier_specification_carrier_specifications_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/carrier-specifications/{specification_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Carrier Specification */
        get: operations["get_carrier_specification_carrier_specifications__specification_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/carrier-specifications/{specification_id}/update": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Update Carrier Specification */
        post: operations["update_carrier_specification_carrier_specifications__specification_id__update_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/carrier-specifications/{specification_id}/deactivate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Deactivate Carrier Specification */
        post: operations["deactivate_carrier_specification_carrier_specifications__specification_id__deactivate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/carrier-specifications/{specification_id}/reactivate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Reactivate Carrier Specification */
        post: operations["reactivate_carrier_specification_carrier_specifications__specification_id__reactivate_post"];
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
    "/farms/{farm_id}/crop-batches/operational-summary": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Crop Batches Operational Summary
         * @description CMP-FE-002A: bounded, farm-wide operational read model -- one
         *     coherent snapshot covering sowing origin, current placement, and open
         *     quality-hold count per batch, powering both Home (`state` omitted,
         *     active-only) and the Batch Register (`state=all`, every legitimate
         *     `crop_batches.state`: active, closed, superseded).
         */
        get: operations["get_crop_batches_operational_summary_farms__farm_id__crop_batches_operational_summary_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/crop-batches/{batch_id}/operational-context": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Crop Batch Operational Context
         * @description Single-batch counterpart of the operational-summary list -- same
         *     shared service function, `{batch_id}` only, so Batch Detail never has
         *     to download the whole farm's payload for one batch's operational
         *     context. Resolves regardless of state (active/closed/superseded).
         */
        get: operations["get_crop_batch_operational_context_farms__farm_id__crop_batches__batch_id__operational_context_get"];
        put?: never;
        post?: never;
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
    "/farms/{farm_id}/seed-lots/{seed_lot_id}/crop-batches": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Batches For Seed Lot
         * @description Section 49: "which Crop Batches were sown from this Seed Lot" --
         *     gated on `seed_lot.read` (the resource being read), matching
         *     `get_seed_lot` above.
         */
        get: operations["list_batches_for_seed_lot_farms__farm_id__seed_lots__seed_lot_id__crop_batches_get"];
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
    "/farms/{farm_id}/nursery/sowings": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Sow New Batch
         * @description NURSERY-OPS-001: the atomic Sowing command -- one call creates
         *     exactly one Crop Batch and its one Sowing Event. Gated on
         *     `sowing.manage` alone: this is a production/operational write, not a
         *     structural configuration change (Farm Setup's `location.manage`/
         *     `asset.manage` do not apply -- the Seeding Station/Seeding Machine are
         *     being USED here, not created).
         */
        post: operations["sow_new_batch_farms__farm_id__nursery_sowings_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/nursery/seed-trays/available": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Available Seed Trays
         * @description Section 16: an active `seed_tray` Carrier with no active Batch-
         *     Carrier-Assignment. Gated on `carrier.read` (the resource actually
         *     being read), not a Sowing-specific permission.
         */
        get: operations["list_available_seed_trays_farms__farm_id__nursery_seed_trays_available_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/germination/trolley-placements": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Place Trolley */
        post: operations["place_trolley_farms__farm_id__germination_trolley_placements_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/germination/tray-placements": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Place Tray */
        post: operations["place_tray_farms__farm_id__germination_tray_placements_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/germination/chambers/available": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Available Chambers */
        get: operations["list_available_chambers_farms__farm_id__germination_chambers_available_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/germination/trolleys/available": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Available Trolleys */
        get: operations["list_available_trolleys_farms__farm_id__germination_trolleys_available_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/germination/trolleys/{trolley_id}/slots": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Trolley Slots */
        get: operations["list_trolley_slots_farms__farm_id__germination_trolleys__trolley_id__slots_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/germination/trays": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Germination Trays */
        get: operations["list_germination_trays_farms__farm_id__germination_trays_get"];
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
    "/farms/{farm_id}/crop-batches/{batch_id}/germination-outcomes": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Germination Outcomes */
        get: operations["list_germination_outcomes_farms__farm_id__crop_batches__batch_id__germination_outcomes_get"];
        put?: never;
        /** Record Germination Outcomes */
        post: operations["record_germination_outcomes_farms__farm_id__crop_batches__batch_id__germination_outcomes_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/crop-batches/{batch_id}/germination-outcomes/current": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Current Germination Outcomes */
        get: operations["get_current_germination_outcomes_farms__farm_id__crop_batches__batch_id__germination_outcomes_current_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/nursery/seedling/entries": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Record Seedling Entry */
        post: operations["record_seedling_entry_farms__farm_id__nursery_seedling_entries_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/nursery/seedling/tables/available": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Available Seedling Tables */
        get: operations["list_available_seedling_tables_farms__farm_id__nursery_seedling_tables_available_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/nursery/seedling/trays": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Seedling Candidate Trays */
        get: operations["list_seedling_candidate_trays_farms__farm_id__nursery_seedling_trays_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/nursery/seedling/dispositions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Seedling Disposition History */
        get: operations["get_seedling_disposition_history_farms__farm_id__nursery_seedling_dispositions_get"];
        put?: never;
        /** Record Seedling Disposition */
        post: operations["record_seedling_disposition_farms__farm_id__nursery_seedling_dispositions_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/nursery/seedling/dispositions/{event_id}/correct": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Correct Seedling Disposition */
        post: operations["correct_seedling_disposition_farms__farm_id__nursery_seedling_dispositions__event_id__correct_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/nursery/seedling/disposition-reasons": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Seedling Disposition Reasons */
        get: operations["list_seedling_disposition_reasons_farms__farm_id__nursery_seedling_disposition_reasons_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/nursery/seedling/biological-trays": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Seedling Biological Trays */
        get: operations["list_seedling_biological_trays_farms__farm_id__nursery_seedling_biological_trays_get"];
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
    "/farms/{farm_id}/crop-batches/{batch_id}/transplants/{event_id}/correct": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Correct Transplant */
        post: operations["correct_transplant_farms__farm_id__crop_batches__batch_id__transplants__event_id__correct_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/crop-batches/{batch_id}/intersalads-transplants": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Record Intersalads Transplant
         * @description NURSERY-OPS-004B.1: one atomic operator command -- biological
         *     Transplant onto Nursery Cultivation Plate destination(s), then physical
         *     placement of each onto its selected InterSalads Table, one transaction.
         *     Gated by `TRANSPLANT_MANAGE` alone (not `MOVEMENT_MANAGE` in addition):
         *     the physical placement is an inseparable side effect of the approved
         *     biological Transplant workflow, and the biological half -- the harder-
         *     to-reverse, dominant operation -- is what this permission represents.
         *     The internal cores perform no permission checks of their own, so this
         *     route declares its own authorization dependency explicitly rather than
         *     assuming one is inherited from `transplants.py`/`movements.py`.
         */
        post: operations["record_intersalads_transplant_farms__farm_id__crop_batches__batch_id__intersalads_transplants_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/nursery/intersalads/available-plates": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Available Intersalads Plates
         * @description NURSERY-OPS-004B.2 section 13: narrow, read-only support for the
         *     InterSalads Transplant operator UI's destination-Plate picker -- not a
         *     generic Carrier-availability framework.
         */
        get: operations["list_available_intersalads_plates_farms__farm_id__nursery_intersalads_available_plates_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/crop-batches/{batch_id}/leafy-production-transfers": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Record Leafy Production Transfer
         * @description NURSERY-OPS-005B: one atomic operator command -- biological
         *     Transplant off Nursery Cultivation Plate source(s) (NURSERY-OPS-005A's
         *     unified source authority, unchanged) onto Production Cultivation Plate
         *     destination(s), then physical placement of each onto its selected Leafy
         *     Production Table, one transaction. Gated by `TRANSPLANT_MANAGE` alone,
         *     mirroring the InterSalads composite's identical rationale: the physical
         *     placement is an inseparable side effect of the approved biological
         *     Transplant, the harder-to-reverse, dominant operation. Never transitions
         *     the Batch's stage -- NURSERY-OPS-005A's own guards remain the Batch's
         *     only stage gates.
         */
        post: operations["record_leafy_production_transfer_farms__farm_id__crop_batches__batch_id__leafy_production_transfers_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/leafy-production/available-sources": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Available Leafy Production Sources
         * @description NURSERY-OPS-005B: narrow, read-only support for the Leafy Production
         *     Transfer operator UI's source-Plate picker -- not a generic "all BCAs
         *     with population" framework. Optional `batch_id` narrows to sources
         *     already established as belonging to the same Batch as a prior
         *     selection; omitted before that first selection is made.
         */
        get: operations["list_available_leafy_production_sources_farms__farm_id__leafy_production_available_sources_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/leafy-production/available-plates": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Available Production Plates
         * @description NURSERY-OPS-005B: narrow, read-only support for the Leafy Production
         *     Transfer operator UI's destination-Plate picker.
         */
        get: operations["list_available_production_plates_farms__farm_id__leafy_production_available_plates_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/leafy-production/dispositions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Production Disposition History */
        get: operations["list_production_disposition_history_farms__farm_id__leafy_production_dispositions_get"];
        put?: never;
        /** Record Production Disposition */
        post: operations["record_production_disposition_farms__farm_id__leafy_production_dispositions_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/leafy-production/dispositions/{event_id}/correct": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Correct Production Disposition */
        post: operations["correct_production_disposition_farms__farm_id__leafy_production_dispositions__event_id__correct_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/leafy-production/active-plates": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Active Production Plates */
        get: operations["list_active_production_plates_farms__farm_id__leafy_production_active_plates_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/leafy-production/harvestable-plates": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Harvestable Plates */
        get: operations["list_harvestable_plates_farms__farm_id__leafy_production_harvestable_plates_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/leafy-production/harvests": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Leafy Harvests */
        get: operations["list_leafy_harvests_farms__farm_id__leafy_production_harvests_get"];
        put?: never;
        /** Record Leafy Harvest */
        post: operations["record_leafy_harvest_farms__farm_id__leafy_production_harvests_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/leafy-production/harvests/{harvest_event_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Leafy Harvest */
        get: operations["get_leafy_harvest_farms__farm_id__leafy_production_harvests__harvest_event_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/farms/{farm_id}/leafy-production/harvests/{harvest_event_id}/source-lines/{harvest_source_line_id}/correct": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Correct Leafy Harvest Source Line */
        post: operations["correct_leafy_harvest_source_line_farms__farm_id__leafy_production_harvests__harvest_event_id__source_lines__harvest_source_line_id__correct_post"];
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
        /**
         * ActiveProductionPlateRead
         * @description The narrow, Leafy-Production-specific active-placements read -- one
         *     row per currently-active (unreleased) Production Cultivation Plate
         *     BatchCarrierAssignment.
         */
        ActiveProductionPlateRead: {
            /**
             * Carrier Id
             * Format: uuid
             */
            carrier_id: string;
            /** Plate Code */
            plate_code: string;
            /**
             * Batch Carrier Assignment Id
             * Format: uuid
             */
            batch_carrier_assignment_id: string;
            /**
             * Population Root Batch Carrier Assignment Id
             * Format: uuid
             */
            population_root_batch_carrier_assignment_id: string;
            /**
             * Batch Id
             * Format: uuid
             */
            batch_id: string;
            /** Batch Code */
            batch_code: string;
            /** Crop Common Name */
            crop_common_name: string;
            /** Variety Name */
            variety_name: string | null;
            /** Opening Population */
            opening_population: number;
            /** Current Living Population */
            current_living_population: number;
            /** Total Recorded Loss */
            total_recorded_loss: number;
            current_location: components["schemas"]["LeafyProductionLocationRead"] | null;
            /** Has Location Warning */
            has_location_warning: boolean;
        };
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
            /** Capacity */
            capacity: number | null;
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
            /** Shelf Capacity */
            shelf_capacity?: number | null;
            /** Slot Capacity */
            slot_capacity?: number | null;
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
        /** AuthMeMembership */
        AuthMeMembership: {
            /**
             * Tenant Id
             * Format: uuid
             */
            tenant_id: string;
            /** Tenant Code */
            tenant_code: string;
            /** Tenant Name */
            tenant_name: string;
            /** Role Code */
            role_code: string;
        };
        /**
         * AuthMeRead
         * @description GET /auth/me's contract. Deliberately excludes oidc_subject, the raw
         *     oidc_issuer, any raw token claims, and the token itself -- only CMP/
         *     application facts a frontend needs to decide what to show next
         *     (login-complete-no-access vs. auto-select vs. tenant picker).
         */
        AuthMeRead: {
            user: components["schemas"]["AuthMeUser"];
            /** Memberships */
            memberships: components["schemas"]["AuthMeMembership"][];
        };
        /** AuthMeUser */
        AuthMeUser: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Email */
            email: string;
            /** Display Name */
            display_name: string;
        };
        /**
         * AvailableLeafyProductionSourceRead
         * @description NURSERY-OPS-005B: one row per `nursery_cultivation_plate`-typed
         *     BatchCarrierAssignment currently eligible as a Leafy Production
         *     Transfer source -- active (unreleased) assignment, positive
         *     authoritative available population resolved through `transplant_
         *     source_authority.get_source_available` only (never a client-side or
         *     hand-summed reconstruction of historical events). Restoration lineage
         *     is handled for free: an assignment query scoped to `released_effective_
         *     time IS NULL` structurally can never return a historical, superseded
         *     generation -- only whichever generation (original or restored) is
         *     currently active is ever a candidate row.
         */
        AvailableLeafyProductionSourceRead: {
            /**
             * Source Assignment Id
             * Format: uuid
             */
            source_assignment_id: string;
            carrier: components["schemas"]["CarrierSummary"];
            /**
             * Batch Id
             * Format: uuid
             */
            batch_id: string;
            /** Batch Code */
            batch_code: string;
            crop: components["schemas"]["CropSummary"];
            variety: components["schemas"]["VarietySummary"] | null;
            /** Authoritative Available Count */
            authoritative_available_count: number;
            current_location: components["schemas"]["LeafyProductionCurrentLocationSummary"] | null;
        };
        /**
         * AvailableNurseryCultivationPlateRead
         * @description NURSERY-OPS-004B.2 section 13: one row per `nursery_cultivation_plate`
         *     Carrier currently eligible as a NEW InterSalads Transplant destination --
         *     active status, no currently-active `BatchCarrierAssignment` (the same
         *     eligibility `_record_transplant_core` itself enforces via
         *     `DestinationCarrierAlreadyAssignedError`, read-only here). Deliberately
         *     reuses `CarrierSpecificationSummary` (`carrier_specification.py`) rather
         *     than inventing a parallel shape.
         */
        AvailableNurseryCultivationPlateRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Code */
            code: string;
            /** Status */
            status: string;
            /** Specification Id */
            specification_id: string | null;
            specification: components["schemas"]["CarrierSpecificationSummary"] | null;
        };
        /**
         * AvailableProductionCultivationPlateRead
         * @description NURSERY-OPS-005B: one row per `production_cultivation_plate` Carrier
         *     currently eligible as a NEW Leafy Production Transfer destination --
         *     active status, no currently-active `BatchCarrierAssignment` -- the same
         *     eligibility `_record_transplant_core` itself enforces via
         *     `DestinationCarrierAlreadyAssignedError`, read-only here. Deliberately
         *     does NOT require "no active Occupancy": Movement legitimately relocates
         *     a Carrier and closes its prior Occupancy as part of the same atomic
         *     move, so a Production Plate already sitting somewhere physically
         *     remains eligible. Mirrors `AvailableNurseryCultivationPlateRead`'s
         *     exact shape, reusing `CarrierSpecificationSummary`.
         */
        AvailableProductionCultivationPlateRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Code */
            code: string;
            /** Status */
            status: string;
            /** Specification Id */
            specification_id: string | null;
            specification: components["schemas"]["CarrierSpecificationSummary"] | null;
        };
        /** AvailableSeedTrayRead */
        AvailableSeedTrayRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Code */
            code: string;
            carrier_type: components["schemas"]["CarrierTypeSummary"];
            /** Specification Id */
            specification_id: string | null;
            specification: components["schemas"]["CarrierSpecificationSummary"] | null;
        };
        /** AvailableSeedlingTableRead */
        AvailableSeedlingTableRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
            /** Capacity */
            capacity: number | null;
            /** Active Tray Count */
            active_tray_count: number;
            /** Remaining Capacity */
            remaining_capacity: number;
            seedling_area: components["schemas"]["SeedlingAreaSummary"];
            greenhouse: components["schemas"]["SeedlingGreenhouseSummary"];
        };
        /** AvailableTrolleyRead */
        AvailableTrolleyRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
            chamber: components["schemas"]["GerminationChamberSummary"];
            /** Total Slot Count */
            total_slot_count: number;
            /** Occupied Slot Count */
            occupied_slot_count: number;
            /** Available Slot Count */
            available_slot_count: number;
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
        /**
         * BatchOperationalContext
         * @description One batch's full operational read model -- shared shape returned by
         *     both the farm-wide summary list and the single-batch context route.
         *     Never includes a UI string; every field is a fact, ID, code, name,
         *     count, or timestamp.
         */
        BatchOperationalContext: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Code */
            code: string;
            crop: components["schemas"]["CropSummary"];
            variety: components["schemas"]["VarietySummary"] | null;
            /** State */
            state: string;
            current_stage: components["schemas"]["OperationalStageSummary"];
            /** Sowing Origins */
            sowing_origins: components["schemas"]["SowingOrigin"][];
            /** Sown Effective Time */
            sown_effective_time: string | null;
            placement: components["schemas"]["PlacementFacts"];
            /** Open Quality Hold Count */
            open_quality_hold_count: number;
        };
        /** BatchPlacement */
        BatchPlacement: {
            /**
             * Carrier Id
             * Format: uuid
             */
            carrier_id: string;
            /** Carrier Code */
            carrier_code: string;
            /**
             * Location Id
             * Format: uuid
             */
            location_id: string;
            /** Location Code */
            location_code: string;
            /** Location Name */
            location_name: string;
            /** Path */
            path: components["schemas"]["LocationPathSegment"][];
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
        /** CarrierBulkCreate */
        CarrierBulkCreate: {
            /** Carrier Type Code */
            carrier_type_code?: string | null;
            /** Specification Id */
            specification_id?: string | null;
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
            carrier_type_code?: string | null;
            /** Specification Id */
            specification_id?: string | null;
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
            /** Specification Id */
            specification_id: string | null;
            specification?: components["schemas"]["CarrierSpecificationSummary"] | null;
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
        /** CarrierSpecificationCreate */
        CarrierSpecificationCreate: {
            /** Carrier Type Code */
            carrier_type_code: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
            /** Length Mm */
            length_mm?: number | null;
            /** Width Mm */
            width_mm?: number | null;
            /** Height Mm */
            height_mm?: number | null;
            /** Biological Position Count */
            biological_position_count?: number | null;
        };
        /** CarrierSpecificationRead */
        CarrierSpecificationRead: {
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
             * Carrier Type Id
             * Format: uuid
             */
            carrier_type_id: string;
            /** Carrier Type Code */
            carrier_type_code: string;
            /** Biological Position Label */
            biological_position_label: string | null;
            /** Code */
            code: string;
            /** Name */
            name: string;
            /** Length Mm */
            length_mm: number | null;
            /** Width Mm */
            width_mm: number | null;
            /** Height Mm */
            height_mm: number | null;
            /** Biological Position Count */
            biological_position_count: number | null;
            /** Status */
            status: string;
            /** Is Structurally Locked */
            is_structurally_locked: boolean;
        };
        /**
         * CarrierSpecificationSummary
         * @description Small, nested summary for embedding inside `CarrierRead` -- avoids
         *     flattening every dimension field onto every Carrier list result while
         *     still avoiding N+1 (resolved via one join in the same list/get query).
         */
        CarrierSpecificationSummary: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
            /** Biological Position Count */
            biological_position_count: number | null;
        };
        /**
         * CarrierSpecificationUpdate
         * @description Full-body update, not a partial PATCH -- the server diffs every
         *     field against the current row and enforces the structural-freeze rule
         *     (section 14) field-by-field. `name` always applies; a structural field
         *     (`carrier_type_code`, `code`, dimensions, `biological_position_count`)
         *     that actually differs from the current value is rejected once any
         *     Carrier already references this specification.
         */
        CarrierSpecificationUpdate: {
            /** Carrier Type Code */
            carrier_type_code: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
            /** Length Mm */
            length_mm?: number | null;
            /** Width Mm */
            width_mm?: number | null;
            /** Height Mm */
            height_mm?: number | null;
            /** Biological Position Count */
            biological_position_count?: number | null;
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
        /** CarrierTypeRead */
        CarrierTypeRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
            /** Requires Specification */
            requires_specification: boolean;
            /** Biological Position Label */
            biological_position_label: string | null;
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
        /** CorrectLeafyHarvestSourceLineCreate */
        CorrectLeafyHarvestSourceLineCreate: {
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            /** Supersedes Correction Id */
            supersedes_correction_id?: string | null;
            /** Is Void */
            is_void: boolean;
            /** Corrected Harvested Weight Kg */
            corrected_harvested_weight_kg?: number | string | null;
            /** Corrected Whole Unit Count */
            corrected_whole_unit_count?: number | null;
            /** Reason Code */
            reason_code: string;
            /** Note */
            note: string;
        };
        /**
         * CorrectProductionDispositionCreate
         * @description `corrected=None` means VOID (reversal only, no replacement); a
         *     populated `corrected` means replace the original with a corrected
         *     biological fact. One atomic command either way.
         */
        CorrectProductionDispositionCreate: {
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            corrected?: components["schemas"]["CorrectedProductionDispositionIn"] | null;
        };
        /**
         * CorrectSeedlingDispositionCreate
         * @description Section 18/0.B: `corrected=None` means VOID (reversal only, no
         *     replacement); a populated `corrected` means replace the original with a
         *     corrected biological fact. One atomic command either way (section 0.A).
         */
        CorrectSeedlingDispositionCreate: {
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            corrected?: components["schemas"]["CorrectedDispositionIn"] | null;
        };
        /** CorrectedDispositionIn */
        CorrectedDispositionIn: {
            /** Quantity */
            quantity: number;
            /** Reason Code */
            reason_code: string;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /** Note */
            note?: string | null;
        };
        /** CorrectedProductionDispositionIn */
        CorrectedProductionDispositionIn: {
            /** Plant Loss Count */
            plant_loss_count: number;
            /** Reason Code */
            reason_code: string;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /** Note */
            note?: string | null;
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
        /** GerminationChamberAvailabilityRead */
        GerminationChamberAvailabilityRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
            /** Trolley Capacity */
            trolley_capacity: number | null;
            /** Active Trolley Count */
            active_trolley_count: number;
            /** Remaining Capacity */
            remaining_capacity: number;
        };
        /**
         * GerminationChamberSetupConfig
         * @description NURSERY-OPS-002A: the Germination Chamber directly occupies Germination
         *     Trolley Assets (the frozen authoritative model -- no chamber_position
         *     child locations). `trolley_capacity` is the number of distinct Trolleys
         *     the Chamber may simultaneously hold -- NULL/1 (DOMAIN-FARM-002 default)
         *     means exclusive, matching the pre-existing capacity convention exactly.
         */
        GerminationChamberSetupConfig: {
            /** Code */
            code: string;
            /** Name */
            name?: string | null;
            /** Trolley Capacity */
            trolley_capacity?: number | null;
        };
        /** GerminationChamberSummary */
        GerminationChamberSummary: {
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
        /** GerminationHandoffSummary */
        GerminationHandoffSummary: {
            /** Normal Seedling Count */
            normal_seedling_count: number;
            /** Abnormal Seedling Count */
            abnormal_seedling_count: number;
            /** Living Seedling Count */
            living_seedling_count: number;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
        };
        /** GerminationOutcomeBatchAggregateRead */
        GerminationOutcomeBatchAggregateRead: {
            /**
             * Batch Id
             * Format: uuid
             */
            batch_id: string;
            /** Batch Code */
            batch_code: string;
            /** Trays */
            trays: components["schemas"]["GerminationOutcomeCurrentRead"][];
            /** Authoritative Living Seedling Total */
            authoritative_living_seedling_total: number;
            /** Completed Tray Count */
            completed_tray_count: number;
            /** Unresolved Tray Count */
            unresolved_tray_count: number;
            /** All Resolved */
            all_resolved: boolean;
        };
        /**
         * GerminationOutcomeCommandCreate
         * @description Dedicated, narrow modern command payload -- never exposes the
         *     generic ObservationEvent `values`/legacy `germination_checks` shape.
         */
        GerminationOutcomeCommandCreate: {
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
            /** Outcomes */
            outcomes: components["schemas"]["GerminationOutcomeIn"][];
        };
        /** GerminationOutcomeCommandRead */
        GerminationOutcomeCommandRead: {
            /**
             * Observation Event Id
             * Format: uuid
             */
            observation_event_id: string;
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
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
            /** Note */
            note: string | null;
            /** Snapshots */
            snapshots: components["schemas"]["GerminationOutcomeSnapshotRead"][];
        };
        /** GerminationOutcomeCurrentRead */
        GerminationOutcomeCurrentRead: {
            /**
             * Batch Carrier Assignment Id
             * Format: uuid
             */
            batch_carrier_assignment_id: string;
            tray: components["schemas"]["CarrierSummary"];
            /**
             * Batch Id
             * Format: uuid
             */
            batch_id: string;
            /** Batch Code */
            batch_code: string;
            /** Seeds Sown */
            seeds_sown: number;
            /** Sown Site Count */
            sown_site_count: number | null;
            /**
             * Current Placement
             * @enum {string}
             */
            current_placement: "awaiting_placement" | "elsewhere" | "in_germination" | "unknown";
            latest_snapshot: components["schemas"]["GerminationOutcomeSnapshotRead"] | null;
            latest_completed_snapshot: components["schemas"]["GerminationOutcomeSnapshotRead"] | null;
            /** Current Normal Seedling Count */
            current_normal_seedling_count: number | null;
            /** Current Abnormal Seedling Count */
            current_abnormal_seedling_count: number | null;
            /** Current Living Seedling Count */
            current_living_seedling_count: number | null;
            /** Current Seed To Living Gap Count */
            current_seed_to_living_gap_count: number | null;
            /** Living Seedling Yield Percent */
            living_seedling_yield_percent: string | null;
            /** Assessment Complete */
            assessment_complete: boolean;
            /** Authoritative Living Seedling Count */
            authoritative_living_seedling_count: number | null;
            /** Latest Effective Time */
            latest_effective_time: string | null;
            /** Historical Snapshot Count */
            historical_snapshot_count: number;
        };
        /** GerminationOutcomeIn */
        GerminationOutcomeIn: {
            /**
             * Batch Carrier Assignment Id
             * Format: uuid
             */
            batch_carrier_assignment_id: string;
            /** Normal Seedling Count */
            normal_seedling_count: number;
            /** Abnormal Seedling Count */
            abnormal_seedling_count: number;
            /** Assessment Complete */
            assessment_complete: boolean;
            /** Note */
            note?: string | null;
        };
        /** GerminationOutcomeSnapshotRead */
        GerminationOutcomeSnapshotRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Observation Event Id
             * Format: uuid
             */
            observation_event_id: string;
            tray: components["schemas"]["CarrierSummary"];
            /**
             * Batch Carrier Assignment Id
             * Format: uuid
             */
            batch_carrier_assignment_id: string;
            /** Normal Seedling Count */
            normal_seedling_count: number;
            /** Abnormal Seedling Count */
            abnormal_seedling_count: number;
            /** Living Seedling Count */
            living_seedling_count: number;
            /** Assessment Complete */
            assessment_complete: boolean;
            /** Note */
            note: string | null;
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
        };
        /** GerminationResolvedPlacement */
        GerminationResolvedPlacement: {
            trolley: components["schemas"]["TrolleySummary"];
            chamber: components["schemas"]["GerminationChamberSummary"];
            slot: components["schemas"]["SlotSummary"];
        };
        /** GerminationTrayRead */
        GerminationTrayRead: {
            /**
             * Batch Id
             * Format: uuid
             */
            batch_id: string;
            /** Batch Code */
            batch_code: string;
            seed_lot: components["schemas"]["SeedLotSummary"];
            tray: components["schemas"]["CarrierSummary"];
            /**
             * Batch Carrier Assignment Id
             * Format: uuid
             */
            batch_carrier_assignment_id: string;
            /** Seeds Sown */
            seeds_sown: number;
            /**
             * State
             * @enum {string}
             */
            state: "awaiting_placement" | "elsewhere" | "in_germination";
            placement: components["schemas"]["GerminationResolvedPlacement"] | null;
        };
        /**
         * GreenhouseOverviewItem
         * @description One row of the Farm Setup Greenhouses overview -- every count is
         *     derived from actual configured `locations` rows, never fabricated.
         */
        GreenhouseOverviewItem: {
            /**
             * Greenhouse Id
             * Format: uuid
             */
            greenhouse_id: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
            /** Classification */
            classification: string;
            /** Status */
            status: string;
            counts: components["schemas"]["GreenhouseSetupCounts"];
        };
        /** GreenhouseSetupCounts */
        GreenhouseSetupCounts: {
            /**
             * Zones
             * @default 0
             */
            zones: number;
            /**
             * Spans
             * @default 0
             */
            spans: number;
            /**
             * Tables
             * @default 0
             */
            tables: number;
            /**
             * Gutters
             * @default 0
             */
            gutters: number;
            /**
             * Bag Positions
             * @default 0
             */
            bag_positions: number;
            /**
             * Seeding Stations
             * @default 0
             */
            seeding_stations: number;
            /**
             * Germination Chambers
             * @default 0
             */
            germination_chambers: number;
            /**
             * Seedling Tables
             * @default 0
             */
            seedling_tables: number;
            /**
             * Intersalads Tables
             * @default 0
             */
            intersalads_tables: number;
            /**
             * Intervines Tables
             * @default 0
             */
            intervines_tables: number;
            /**
             * Trolleys
             * @default 0
             */
            trolleys: number;
            /**
             * Trolley Levels
             * @default 0
             */
            trolley_levels: number;
            /**
             * Trolley Slots
             * @default 0
             */
            trolley_slots: number;
            /**
             * Seeding Machines
             * @default 0
             */
            seeding_machines: number;
        };
        /** GreenhouseSetupCreate */
        GreenhouseSetupCreate: {
            /** Code */
            code: string;
            /** Name */
            name: string;
            /** Classification */
            classification: string;
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            nursery?: components["schemas"]["NurserySetupConfig"] | null;
            leafy?: components["schemas"]["LeafySetupConfig"] | null;
            vines?: components["schemas"]["VinesSetupConfig"] | null;
        };
        /** GreenhouseSetupResult */
        GreenhouseSetupResult: {
            /**
             * Greenhouse Id
             * Format: uuid
             */
            greenhouse_id: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
            /** Classification */
            classification: string;
            counts: components["schemas"]["GreenhouseSetupCounts"];
        };
        /**
         * GreenhouseStructureRead
         * @description A readable, classification-shaped view of one Greenhouse's existing
         *     physical structure -- not a generic Location dump. Exactly one of the
         *     three classification-specific groups below is populated, matching
         *     `greenhouse.classification`.
         */
        GreenhouseStructureRead: {
            /**
             * Greenhouse Id
             * Format: uuid
             */
            greenhouse_id: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
            /** Classification */
            classification: string;
            /** Leafy Zones */
            leafy_zones?: components["schemas"]["StructureZoneNode"][] | null;
            /** Vines Zones */
            vines_zones?: components["schemas"]["StructureVinesZoneNode"][] | null;
            /** Nursery Seeding Stations */
            nursery_seeding_stations?: components["schemas"]["StructureSectionNode"][];
            nursery_germination_chamber?: components["schemas"]["StructureGerminationChamberNode"] | null;
            nursery_seedling?: components["schemas"]["StructureNurseryTableGroup"] | null;
            nursery_intersalads?: components["schemas"]["StructureNurseryTableGroup"] | null;
            nursery_intervines?: components["schemas"]["StructureNurseryTableGroup"] | null;
        };
        /**
         * GutterGeneratorConfig
         * @description Generates N sibling Grow Gutters under one Span, each with the same
         *     number of Grow Bag Positions. Grow Bag Position is a true exclusive
         *     physical position -- its capacity is never configurable here and is
         *     always left at the domain default (NULL -> effective capacity 1);
         *     this model has no `capacity` field at all, deliberately, so there is no
         *     biological/plant-capacity input to misuse.
         */
        GutterGeneratorConfig: {
            /** Code Prefix */
            code_prefix: string;
            /** Start */
            start: number;
            /** End */
            end: number;
            /** Pad Width */
            pad_width: number;
            /** Bag Positions Per Gutter */
            bag_positions_per_gutter: number;
            /** Bag Position Code Prefix */
            bag_position_code_prefix: string;
            /** Bag Position Pad Width */
            bag_position_pad_width: number;
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
        /**
         * HarvestablePlateRead
         * @description One row per currently-eligible Leafy Harvest source: an active
         *     (unreleased) `production_cultivation_plate` BatchCarrierAssignment with
         *     positive current living population (Slice-1 shared authority). A
         *     zero-living Plate never appears here (it disappears from the
         *     harvestable list once fully harvested) but remains discoverable via
         *     Harvest history. A quality-held Plate DOES still appear here (visibly
         *     flagged, never hidden) -- the write endpoint remains the sole
         *     authority that actually blocks a new Harvest while the hold is open.
         *     Deliberately omits the internal population-root BatchCarrierAssignment
         *     id -- never genuinely useful to the operator-facing client.
         */
        HarvestablePlateRead: {
            /**
             * Production Plate Id
             * Format: uuid
             */
            production_plate_id: string;
            /** Production Plate Code */
            production_plate_code: string;
            /**
             * Batch Id
             * Format: uuid
             */
            batch_id: string;
            /** Batch Code */
            batch_code: string;
            /** Crop Common Name */
            crop_common_name: string;
            /** Variety Name */
            variety_name: string | null;
            /** Current Living Heads */
            current_living_heads: number;
            /**
             * Current Batch Carrier Assignment Id
             * Format: uuid
             */
            current_batch_carrier_assignment_id: string;
            location: components["schemas"]["LeafyHarvestLocationRead"] | null;
            /** Has Location Warning */
            has_location_warning: boolean;
            /** Quality Hold Open */
            quality_hold_open: boolean;
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
        /**
         * IntersaladsDestinationLineIn
         * @description One destination Nursery Cultivation Plate: the biological quantity
         *     assigned to it (`assigned_plant_count`, reconciled by the existing
         *     Transplant core exactly as for the generic endpoint) plus the InterSalads
         *     Table it must be physically placed on in the same atomic command
         *     (`destination_location_id`) -- the one genuinely new fact the generic
         *     `TransplantDestinationLineIn` does not and must not carry.
         */
        IntersaladsDestinationLineIn: {
            /**
             * Destination Carrier Id
             * Format: uuid
             */
            destination_carrier_id: string;
            /** Assigned Plant Count */
            assigned_plant_count: number;
            /**
             * Destination Location Id
             * Format: uuid
             */
            destination_location_id: string;
            /** Note */
            note?: string | null;
        };
        /**
         * IntersaladsDestinationLineRead
         * @description Section 19 of the ticket: the composite response must be
         *     reconstructible identically on exact replay -- every field here is
         *     re-derivable from already-committed TransplantDestinationLine + Movement
         *     rows, never from in-memory-only state.
         */
        IntersaladsDestinationLineRead: {
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
            /**
             * Destination Location Id
             * Format: uuid
             */
            destination_location_id: string;
            /**
             * Movement Id
             * Format: uuid
             */
            movement_id: string;
            /** Note */
            note: string | null;
        };
        /**
         * IntersaladsTransplantCreate
         * @description Mirrors `TransplantEventCreate`'s own structure and validation
         *     intent exactly (including the established duplicate-destination-carrier
         *     prohibition -- section 4's revalidation confirmed this is already the
         *     generic Transplant domain's existing semantics, not a new
         *     interpretation), substituting `IntersaladsDestinationLineIn` for
         *     `TransplantDestinationLineIn`.
         */
        IntersaladsTransplantCreate: {
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
            destination_lines: components["schemas"]["IntersaladsDestinationLineIn"][];
            /** Allocations */
            allocations: components["schemas"]["TransplantAllocationIn"][];
        };
        /** IntersaladsTransplantRead */
        IntersaladsTransplantRead: {
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
            destination_lines: components["schemas"]["IntersaladsDestinationLineRead"][];
            /** Allocations */
            allocations: components["schemas"]["TransplantAllocationRead"][];
            /** Total Source Available Before */
            total_source_available_before: number;
            /** Total Destination Plant Count */
            total_destination_plant_count: number;
            /** Total Discarded Plant Count */
            total_discarded_plant_count: number;
            /** Total Remainder After */
            total_remainder_after: number;
        };
        /**
         * LeafyHarvestEventRead
         * @description One HarvestEvent/HarvestedProduceLot pair, Leafy-aware. `original_*`
         *     mirrors `HarvestedProduceLot.total_*` (immutable, never presented as
         *     current truth on its own). `current_*` is the aggregation of every
         *     source line's own current effective tuple (Slice-1's correction chain
         *     authority) -- may equal `original_*` in total even when individual
         *     lines changed in offsetting directions; per-line values in
         *     `source_lines` remain the only place that distinction is visible.
         *     `available_balance_*` is the produce lot's CURRENT ledger balance
         *     (after any downstream Packing consumption) -- deliberately a different
         *     number from `current_*`, never conflated with it.
         */
        LeafyHarvestEventRead: {
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
            crop: components["schemas"]["CropSummary"];
            variety: components["schemas"]["VarietySummary"] | null;
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
             * Produce Lot Id
             * Format: uuid
             */
            produce_lot_id: string;
            /** Produce Lot Code */
            produce_lot_code: string;
            /** Note */
            note: string | null;
            /** Original Total Harvested Weight Kg */
            original_total_harvested_weight_kg: string;
            /** Original Total Whole Unit Count */
            original_total_whole_unit_count: number | null;
            /** Current Total Harvested Weight Kg */
            current_total_harvested_weight_kg: string;
            /** Current Total Whole Unit Count */
            current_total_whole_unit_count: number;
            /** Available Balance Weight Kg */
            available_balance_weight_kg: string;
            /** Available Balance Whole Unit Count */
            available_balance_whole_unit_count: number | null;
            /** Source Lines */
            source_lines: components["schemas"]["LeafyHarvestSourceLineRead"][];
        };
        /**
         * LeafyHarvestLocationRead
         * @description One Location breakdown, broken out by the fixed Leafy chain (`zone ->
         *     span -> grow_table`, always under one `greenhouse`) -- resolved by
         *     walking `parent_location_id` and slotting each ancestor by its own
         *     `location_type_code`, never by a hardcoded depth (CLAUDE.md: generic,
         *     UUID-based parent-child locations). Operator context only, never
         *     biological authority. Reused for two DELIBERATELY DIFFERENT-MEANING
         *     fields (never conflate them): `HarvestablePlateRead.location` is the
         *     Plate's CURRENT physical Occupancy target (operational, live);
         *     `LeafyHarvestSourceLineRead.harvest_location` is the Plate's HISTORICAL
         *     Occupancy target as of the HarvestEvent's own `effective_time` (a
         *     traceability fact, frozen at Harvest time, unaffected by any later
         *     Movement).
         */
        LeafyHarvestLocationRead: {
            greenhouse: components["schemas"]["LeafyLocationSlotRead"] | null;
            zone: components["schemas"]["LeafyLocationSlotRead"] | null;
            span: components["schemas"]["LeafyLocationSlotRead"] | null;
            grow_table: components["schemas"]["LeafyLocationSlotRead"] | null;
        };
        /** LeafyHarvestSourceLineCorrectionRead */
        LeafyHarvestSourceLineCorrectionRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Supersedes Correction Id */
            supersedes_correction_id: string | null;
            /** Is Void */
            is_void: boolean;
            /** Corrected Harvested Weight Kg */
            corrected_harvested_weight_kg: string | null;
            /** Corrected Whole Unit Count */
            corrected_whole_unit_count: number | null;
            /** Reason Code */
            reason_code: string;
            /** Note */
            note: string;
            /** Actor User Id */
            actor_user_id: string | null;
            /**
             * Recorded Time
             * Format: date-time
             */
            recorded_time: string;
        };
        /**
         * LeafyHarvestSourceLineRead
         * @description Both the immutable ORIGINAL fact and the structurally-resolved
         *     CURRENT effective truth for one source contribution -- never collapses
         *     one into the other. `state` is `"VOID"` only when the correction chain
         *     tip is a void correction; otherwise `"ACTIVE"` (including when never
         *     corrected at all). `correction_tip_id` is the id the client MUST echo
         *     back as `supersedes_correction_id` on its next correction attempt (a
         *     stale value there is rejected with 409, never silently retargeted).
         */
        LeafyHarvestSourceLineRead: {
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
            harvest_location: components["schemas"]["LeafyHarvestLocationRead"] | null;
            /** Original Harvested Weight Kg */
            original_harvested_weight_kg: string;
            /** Original Whole Unit Count */
            original_whole_unit_count: number | null;
            /** Current Harvested Weight Kg */
            current_harvested_weight_kg: string;
            /** Current Whole Unit Count */
            current_whole_unit_count: number;
            /**
             * State
             * @enum {string}
             */
            state: "ACTIVE" | "VOID";
            /** Correction Tip Id */
            correction_tip_id: string | null;
            /** Correction History */
            correction_history: components["schemas"]["LeafyHarvestSourceLineCorrectionRead"][];
        };
        /** LeafyLocationSlotRead */
        LeafyLocationSlotRead: {
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
        /**
         * LeafyProductionCurrentLocationSummary
         * @description The source Plate's current physical Occupancy target, if any --
         *     operator context only, never a biological-eligibility fact (NURSERY-
         *     OPS-005B section 3: physical InterSalads location is informational,
         *     the authoritative source_assignment_id/authoritative_available_count
         *     above are what make a Plate a valid source).
         */
        LeafyProductionCurrentLocationSummary: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
            /** Location Type Code */
            location_type_code: string;
        };
        /**
         * LeafyProductionDestinationLineIn
         * @description One destination Production Cultivation Plate: the biological
         *     quantity assigned to it (`assigned_plant_count`, reconciled by the
         *     existing Transplant core exactly as for the generic endpoint) plus the
         *     Leafy Production Table it must be physically placed on in the same
         *     atomic command (`destination_location_id` -- the Table itself, the only
         *     write-authoritative location identifier; Greenhouse/Zone/Span ids are
         *     frontend-only UX state for narrowing the picker, never sent here since
         *     backend semantics need only the final Table).
         */
        LeafyProductionDestinationLineIn: {
            /**
             * Destination Carrier Id
             * Format: uuid
             */
            destination_carrier_id: string;
            /** Assigned Plant Count */
            assigned_plant_count: number;
            /**
             * Destination Location Id
             * Format: uuid
             */
            destination_location_id: string;
            /** Note */
            note?: string | null;
        };
        /**
         * LeafyProductionDestinationLineRead
         * @description Every field here is re-derivable from already-committed
         *     TransplantDestinationLine + Movement rows, never in-memory-only state --
         *     the composite's response stays identical on exact replay, mirroring
         *     `IntersaladsDestinationLineRead`'s own proven shape.
         */
        LeafyProductionDestinationLineRead: {
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
            /**
             * Destination Location Id
             * Format: uuid
             */
            destination_location_id: string;
            /**
             * Movement Id
             * Format: uuid
             */
            movement_id: string;
            /** Note */
            note: string | null;
        };
        /**
         * LeafyProductionLocationRead
         * @description Operator context only, never biological authority -- mirrors
         *     NURSERY-OPS-005B's own `LeafyProductionCurrentLocationSummary`.
         */
        LeafyProductionLocationRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
            /** Location Type Code */
            location_type_code: string;
            /** Ancestry Label */
            ancestry_label: string;
        };
        /**
         * LeafyProductionTransferCreate
         * @description Mirrors `IntersaladsTransplantCreate`'s own structure and validation
         *     intent exactly, substituting `LeafyProductionDestinationLineIn` for
         *     `IntersaladsDestinationLineIn` -- same duplicate-id/undeclared-reference/
         *     every-destination-allocated invariants, proven correct by that
         *     precedent, not reinvented here.
         */
        LeafyProductionTransferCreate: {
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
            destination_lines: components["schemas"]["LeafyProductionDestinationLineIn"][];
            /** Allocations */
            allocations: components["schemas"]["TransplantAllocationIn"][];
        };
        /** LeafyProductionTransferRead */
        LeafyProductionTransferRead: {
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
            destination_lines: components["schemas"]["LeafyProductionDestinationLineRead"][];
            /** Allocations */
            allocations: components["schemas"]["TransplantAllocationRead"][];
            /** Total Source Available Before */
            total_source_available_before: number;
            /** Total Destination Plant Count */
            total_destination_plant_count: number;
            /** Total Discarded Plant Count */
            total_discarded_plant_count: number;
            /** Total Remainder After */
            total_remainder_after: number;
        };
        /** LeafySetupConfig */
        LeafySetupConfig: {
            /** Zones */
            zones: components["schemas"]["ZoneSetupConfig"][];
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
        /** LocationAggregateCount */
        LocationAggregateCount: {
            /**
             * Location Id
             * Format: uuid
             */
            location_id: string;
            /** Occupiable Location Count */
            occupiable_location_count: number;
            /** Occupied Location Count */
            occupied_location_count: number;
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
            /** Capacity */
            capacity?: number | null;
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
            /** Capacity */
            capacity?: number | null;
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
        /** LocationOccupant */
        LocationOccupant: {
            /** Kind */
            kind: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Carrier Code */
            carrier_code: string | null;
            batch: components["schemas"]["OccupantBatchContext"] | null;
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
        /** LocationPathSegment */
        LocationPathSegment: {
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
            /** Capacity */
            capacity: number | null;
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
            /** Capacity */
            capacity: number | null;
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
        /**
         * NurserySectionConfig
         * @description FARM-SETUP-001.1: Seeding Station / Germination Chamber -- a single
         *     physical section directly under the Nursery Greenhouse, user-supplied
         *     code (never a generated/hidden identity, unlike the table generators --
         *     there is exactly one of each per Nursery, not "N of them").
         */
        NurserySectionConfig: {
            /** Code */
            code: string;
            /** Name */
            name?: string | null;
        };
        /**
         * NurserySetupConfig
         * @description Section 7 (Seedling/InterSalads/InterVines tables) plus sections 8-9
         *     (optional Germination Trolley/Seeding Machine assets) plus
         *     FARM-SETUP-001.1's Seeding Station / Germination Chamber -- the
         *     complete authoritative Nursery topology is now configurable entirely
         *     inside Farm Setup, no generic Location API workaround required.
         */
        NurserySetupConfig: {
            seeding_station?: components["schemas"]["NurserySectionConfig"] | null;
            germination_chamber?: components["schemas"]["GerminationChamberSetupConfig"] | null;
            seedling_tables?: components["schemas"]["TableGeneratorConfig"] | null;
            intersalads_tables?: components["schemas"]["TableGeneratorConfig"] | null;
            intervines_tables?: components["schemas"]["TableGeneratorConfig"] | null;
            /** Trolleys */
            trolleys?: components["schemas"]["TrolleySetupConfig"][];
            /** Seeding Machines */
            seeding_machines?: components["schemas"]["SeedingMachineSetupConfig"][];
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
        /** OccupantBatchContext */
        OccupantBatchContext: {
            /**
             * Batch Id
             * Format: uuid
             */
            batch_id: string;
            /** Batch Code */
            batch_code: string;
            crop: components["schemas"]["CropSummary"];
            current_stage: components["schemas"]["OperationalStageSummary"];
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
        /** OccupiedLocation */
        OccupiedLocation: {
            /**
             * Location Id
             * Format: uuid
             */
            location_id: string;
            occupant: components["schemas"]["LocationOccupant"];
            /** Occupants */
            occupants: components["schemas"]["LocationOccupant"][];
        };
        /**
         * OperationalStageSummary
         * @description CMP-FE-002A.1: `StageSummary` (crop_batch.py) is shared across many
         *     unrelated response contracts (sowing/harvest/transplant events, quality
         *     holds, observation events, batch derivation, core crop-batch reads) --
         *     adding `stage_category` there would widen every one of those contracts
         *     for a need specific to the three operational-read endpoints. This type
         *     exists only for that operational-read family (`BatchOperationalContext`,
         *     `OccupantBatchContext`) and adds the one authoritative field FE-002B
         *     needs to classify a batch's readiness (e.g. `stage_category ==
         *     "harvest_ready"`) without inferring it from stage name/code.
         */
        OperationalStageSummary: {
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
            /** Stage Category */
            stage_category: string;
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
        /** PlaceTrayCreate */
        PlaceTrayCreate: {
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            /**
             * Tray Id
             * Format: uuid
             */
            tray_id: string;
            /**
             * Trolley Id
             * Format: uuid
             */
            trolley_id: string;
            /**
             * Slot Id
             * Format: uuid
             */
            slot_id: string;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /** Reason */
            reason?: string | null;
        };
        /** PlaceTrolleyCreate */
        PlaceTrolleyCreate: {
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            /**
             * Trolley Id
             * Format: uuid
             */
            trolley_id: string;
            /**
             * Chamber Id
             * Format: uuid
             */
            chamber_id: string;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /** Reason */
            reason?: string | null;
        };
        /**
         * PlacementFacts
         * @description Structured current-placement truth for one batch. `active_*_count`
         *     always partitions exactly (`active = placed + unplaced`) -- proven by
         *     the database's own partial-unique constraint that a carrier has at
         *     most one active occupancy at a time (`ux_occupancies_active_occupant_carrier`).
         */
        PlacementFacts: {
            /** Active Carrier Count */
            active_carrier_count: number;
            /** Placed Carrier Count */
            placed_carrier_count: number;
            /** Unplaced Carrier Count */
            unplaced_carrier_count: number;
            /** Placements */
            placements: components["schemas"]["BatchPlacement"][];
            /** Common Ancestor Path */
            common_ancestor_path: components["schemas"]["LocationPathSegment"][] | null;
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
        /** ProductionDispositionCorrectResult */
        ProductionDispositionCorrectResult: {
            /**
             * Command Id
             * Format: uuid
             */
            command_id: string;
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            /**
             * Population Root Batch Carrier Assignment Id
             * Format: uuid
             */
            population_root_batch_carrier_assignment_id: string;
            target_event: components["schemas"]["ProductionDispositionEventRead"];
            reversal_event: components["schemas"]["ProductionDispositionEventRead"];
            replacement_event: components["schemas"]["ProductionDispositionEventRead"] | null;
            /** Restored Batch Carrier Assignment Id */
            restored_batch_carrier_assignment_id: string | null;
            /** Previous Living Population */
            previous_living_population: number;
            /** Resulting Living Population */
            resulting_living_population: number;
        };
        /** ProductionDispositionEventRead */
        ProductionDispositionEventRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Command Id
             * Format: uuid
             */
            command_id: string;
            /**
             * Batch Carrier Assignment Id
             * Format: uuid
             */
            batch_carrier_assignment_id: string;
            /**
             * Population Root Batch Carrier Assignment Id
             * Format: uuid
             */
            population_root_batch_carrier_assignment_id: string;
            /**
             * Event Kind
             * @enum {string}
             */
            event_kind: "REDUCTION" | "REVERSAL";
            /** Reason Code */
            reason_code: string;
            /** Quantity Delta */
            quantity_delta: number;
            /** Plant Loss Quantity */
            plant_loss_quantity: number;
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
            /** Note */
            note: string | null;
            /** Reverses Event Id */
            reverses_event_id: string | null;
            /** Corrects Event Id */
            corrects_event_id: string | null;
            /** Is Reversed */
            is_reversed: boolean;
            /** Actor User Id */
            actor_user_id: string | null;
        };
        /**
         * ProductionDispositionHistoryRead
         * @description Full, un-collapsed event history for one population lineage -- never
         *     hides original erroneous facts; corrections are visible as their own
         *     rows with explicit linkage. Remains accessible after the lineage's
         *     active BCA is released (section 30 of the ticket: a zero-exhausted
         *     Plate must stay discoverable here even though it disappears from
         *     Active Production Plates).
         */
        ProductionDispositionHistoryRead: {
            /**
             * Population Root Batch Carrier Assignment Id
             * Format: uuid
             */
            population_root_batch_carrier_assignment_id: string;
            /** Plate Code */
            plate_code: string;
            /**
             * Batch Id
             * Format: uuid
             */
            batch_id: string;
            /** Batch Code */
            batch_code: string;
            /** Opening Population */
            opening_population: number;
            /** Current Living Population */
            current_living_population: number;
            /** Is Active */
            is_active: boolean;
            /** Events */
            events: components["schemas"]["ProductionDispositionEventRead"][];
        };
        /** ProductionDispositionRecordResult */
        ProductionDispositionRecordResult: {
            /**
             * Command Id
             * Format: uuid
             */
            command_id: string;
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            /**
             * Batch Carrier Assignment Id
             * Format: uuid
             */
            batch_carrier_assignment_id: string;
            /**
             * Population Root Batch Carrier Assignment Id
             * Format: uuid
             */
            population_root_batch_carrier_assignment_id: string;
            event: components["schemas"]["ProductionDispositionEventRead"];
            /** Previous Living Population */
            previous_living_population: number;
            /** Resulting Living Population */
            resulting_living_population: number;
            /** Assignment Released */
            assignment_released: boolean;
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
        /** RecordLeafyHarvestCreate */
        RecordLeafyHarvestCreate: {
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
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
            /** Produce Lot Code */
            produce_lot_code: string;
            /** Note */
            note?: string | null;
            /** Source Lines */
            source_lines: components["schemas"]["RecordLeafyHarvestSourceLineIn"][];
        };
        /** RecordLeafyHarvestSourceLineIn */
        RecordLeafyHarvestSourceLineIn: {
            /**
             * Batch Carrier Assignment Id
             * Format: uuid
             */
            batch_carrier_assignment_id: string;
            /** Whole Unit Count */
            whole_unit_count: number;
            /** Harvested Weight Kg */
            harvested_weight_kg: number | string;
            /** Note */
            note?: string | null;
        };
        /**
         * RecordProductionDispositionCreate
         * @description The operator supplies only physical/biological command facts -- a
         *     positive `plant_loss_count`, never a signed delta. The service
         *     translates this into `quantity_delta = -plant_loss_count`.
         */
        RecordProductionDispositionCreate: {
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            /**
             * Batch Carrier Assignment Id
             * Format: uuid
             */
            batch_carrier_assignment_id: string;
            /** Plant Loss Count */
            plant_loss_count: number;
            /** Reason Code */
            reason_code: string;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /** Note */
            note?: string | null;
        };
        /**
         * RecordSeedlingDispositionCreate
         * @description Section 17: the operator supplies only physical/biological command
         *     facts -- a positive `quantity`, never a signed delta, never a current
         *     or starting balance.
         */
        RecordSeedlingDispositionCreate: {
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            /**
             * Batch Carrier Assignment Id
             * Format: uuid
             */
            batch_carrier_assignment_id: string;
            /** Quantity */
            quantity: number;
            /** Reason Code */
            reason_code: string;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /** Note */
            note?: string | null;
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
        /** ResolvedPhysicalPlacement */
        ResolvedPhysicalPlacement: {
            /**
             * Kind
             * @enum {string}
             */
            kind: "unplaced" | "in_germination" | "on_seedling_table" | "elsewhere";
            germination: components["schemas"]["GerminationResolvedPlacement"] | null;
            seedling_table: components["schemas"]["SeedlingTableSummary"] | null;
        };
        /**
         * SeedLotBatchSummary
         * @description NURSERY-OPS-001 section 49: the reverse of 'which Seed Lot created
         *     this Batch' -- a simple related-batches read, not a traceability UI.
         */
        SeedLotBatchSummary: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Code */
            code: string;
            /**
             * Sown Effective Time
             * Format: date-time
             */
            sown_effective_time: string;
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
        /** SeedingMachineSetupConfig */
        SeedingMachineSetupConfig: {
            /** Code */
            code: string;
            /** Name */
            name?: string | null;
        };
        /** SeedingMachineSummary */
        SeedingMachineSummary: {
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
        /** SeedingStationSummary */
        SeedingStationSummary: {
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
        /** SeedlingAreaSummary */
        SeedlingAreaSummary: {
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
        /**
         * SeedlingBiologicalTrayRead
         * @description Section 54/57: the dedicated Seedling-page read -- per Tray that has
         *     a `SeedlingEntry`, the frozen start, the derived current balance, and
         *     enough context to drive both the record and correction UI without a
         *     second round-trip.
         *
         *     NURSERY-OPS-004A section 27/28: `current_living_seedling_count` keeps
         *     its UNCHANGED 003B meaning -- all living plants ever accounted for by
         *     this Tray's disposition history, checkpoint-unaware. It does NOT mean
         *     "still available to transplant" once any checkpoint exists.
         *     `current_source_available_count` is the new, checkpoint/transplant-
         *     aware figure operators must use to decide how many plants remain
         *     transplantable right now.
         */
        SeedlingBiologicalTrayRead: {
            /**
             * Batch Id
             * Format: uuid
             */
            batch_id: string;
            /** Batch Code */
            batch_code: string;
            /**
             * Tray Id
             * Format: uuid
             */
            tray_id: string;
            /** Tray Code */
            tray_code: string;
            /** Crop Common Name */
            crop_common_name: string;
            /** Variety Name */
            variety_name: string;
            /** Seed Lot Code */
            seed_lot_code: string;
            /**
             * Batch Carrier Assignment Id
             * Format: uuid
             */
            batch_carrier_assignment_id: string;
            /**
             * Seedling Entry Id
             * Format: uuid
             */
            seedling_entry_id: string;
            /** Starting Living Seedling Count */
            starting_living_seedling_count: number;
            /** Total Reduction Magnitude */
            total_reduction_magnitude: number;
            /** Total Reversal Magnitude */
            total_reversal_magnitude: number;
            /** Current Living Seedling Count */
            current_living_seedling_count: number;
            /** Current Source Available Count */
            current_source_available_count: number;
            /** Checkpoint Count */
            checkpoint_count: number;
            /** Latest Checkpoint Id */
            latest_checkpoint_id: string | null;
            /** Latest Checkpoint Effective Time */
            latest_checkpoint_effective_time: string | null;
            /** Latest Checkpoint Remainder After */
            latest_checkpoint_remainder_after: number | null;
            /** Is Depleted */
            is_depleted: boolean;
            /** Event Count */
            event_count: number;
            /** Seedling Table Id */
            seedling_table_id: string | null;
            /** Seedling Table Code */
            seedling_table_code: string | null;
            /** Assignment Active */
            assignment_active: boolean;
            /** Assignment Released Effective Time */
            assignment_released_effective_time: string | null;
        };
        /** SeedlingCandidateTrayRead */
        SeedlingCandidateTrayRead: {
            /**
             * Batch Id
             * Format: uuid
             */
            batch_id: string;
            /** Batch Code */
            batch_code: string;
            seed_lot: components["schemas"]["SeedLotSummary"];
            tray: components["schemas"]["CarrierSummary"];
            /**
             * Batch Carrier Assignment Id
             * Format: uuid
             */
            batch_carrier_assignment_id: string;
            /** Seeds Sown */
            seeds_sown: number;
            germination_handoff: components["schemas"]["GerminationHandoffSummary"] | null;
            seedling_entry: components["schemas"]["SeedlingEntrySummary"] | null;
            current_placement: components["schemas"]["ResolvedPhysicalPlacement"];
            /**
             * State
             * @enum {string}
             */
            state: "no_completed_handoff" | "ready_for_seedling" | "in_seedling" | "in_seedling_unanchored" | "elsewhere";
        };
        /** SeedlingDispositionCorrectResult */
        SeedlingDispositionCorrectResult: {
            /**
             * Command Id
             * Format: uuid
             */
            command_id: string;
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            /**
             * Seedling Entry Id
             * Format: uuid
             */
            seedling_entry_id: string;
            target_event: components["schemas"]["SeedlingDispositionEventRead"];
            reversal_event: components["schemas"]["SeedlingDispositionEventRead"];
            replacement_event: components["schemas"]["SeedlingDispositionEventRead"] | null;
            /** Previous Living Seedling Count */
            previous_living_seedling_count: number;
            /** Resulting Living Seedling Count */
            resulting_living_seedling_count: number;
        };
        /** SeedlingDispositionEventRead */
        SeedlingDispositionEventRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Command Id
             * Format: uuid
             */
            command_id: string;
            /**
             * Seedling Entry Id
             * Format: uuid
             */
            seedling_entry_id: string;
            /**
             * Event Kind
             * @enum {string}
             */
            event_kind: "REDUCTION" | "REVERSAL";
            /** Reason Code */
            reason_code: string;
            /** Quantity Delta */
            quantity_delta: number;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /** Note */
            note: string | null;
            /** Reverses Event Id */
            reverses_event_id: string | null;
            /** Corrects Event Id */
            corrects_event_id: string | null;
            /** Actor User Id */
            actor_user_id: string | null;
            /**
             * Recorded At
             * Format: date-time
             */
            recorded_at: string;
        };
        /**
         * SeedlingDispositionHistoryRead
         * @description Full, un-collapsed event history for one Tray -- section 55: never
         *     hides original erroneous facts; corrections are visible as their own
         *     rows with explicit linkage.
         */
        SeedlingDispositionHistoryRead: {
            /**
             * Seedling Entry Id
             * Format: uuid
             */
            seedling_entry_id: string;
            /** Starting Living Seedling Count */
            starting_living_seedling_count: number;
            /** Current Living Seedling Count */
            current_living_seedling_count: number;
            /** Events */
            events: components["schemas"]["SeedlingDispositionEventRead"][];
        };
        /** SeedlingDispositionReasonRead */
        SeedlingDispositionReasonRead: {
            /** Code */
            code: string;
            /** Name */
            name: string;
        };
        /** SeedlingDispositionRecordResult */
        SeedlingDispositionRecordResult: {
            /**
             * Command Id
             * Format: uuid
             */
            command_id: string;
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            /**
             * Seedling Entry Id
             * Format: uuid
             */
            seedling_entry_id: string;
            event: components["schemas"]["SeedlingDispositionEventRead"];
            /** Previous Living Seedling Count */
            previous_living_seedling_count: number;
            /** Quantity Delta */
            quantity_delta: number;
            /** Resulting Living Seedling Count */
            resulting_living_seedling_count: number;
        };
        /**
         * SeedlingEntryCreate
         * @description Section 26: the operator supplies only physical/handoff-command
         *     facts -- `starting_living_seedling_count` and
         *     `source_germination_outcome_snapshot_id` are never accepted from the
         *     caller; the server always resolves and freezes them authoritatively
         *     (section 10/11).
         */
        SeedlingEntryCreate: {
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            /**
             * Batch Carrier Assignment Id
             * Format: uuid
             */
            batch_carrier_assignment_id: string;
            /**
             * Destination Seedling Table Id
             * Format: uuid
             */
            destination_seedling_table_id: string;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /** Reason */
            reason?: string | null;
        };
        /** SeedlingEntryRead */
        SeedlingEntryRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            /**
             * Batch Id
             * Format: uuid
             */
            batch_id: string;
            /** Batch Code */
            batch_code: string;
            /**
             * Batch Carrier Assignment Id
             * Format: uuid
             */
            batch_carrier_assignment_id: string;
            tray: components["schemas"]["CarrierSummary"];
            seedling_table: components["schemas"]["SeedlingTableSummary"];
            /**
             * Movement Id
             * Format: uuid
             */
            movement_id: string;
            /**
             * Source Germination Outcome Snapshot Id
             * Format: uuid
             */
            source_germination_outcome_snapshot_id: string;
            /** Source Normal Seedling Count */
            source_normal_seedling_count: number;
            /** Source Abnormal Seedling Count */
            source_abnormal_seedling_count: number;
            /**
             * Source Effective Time
             * Format: date-time
             */
            source_effective_time: string;
            /** Starting Living Seedling Count */
            starting_living_seedling_count: number;
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
        };
        /** SeedlingEntrySummary */
        SeedlingEntrySummary: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Movement Id
             * Format: uuid
             */
            movement_id: string;
            /**
             * Source Germination Outcome Snapshot Id
             * Format: uuid
             */
            source_germination_outcome_snapshot_id: string;
            /** Starting Living Seedling Count */
            starting_living_seedling_count: number;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
        };
        /** SeedlingGreenhouseSummary */
        SeedlingGreenhouseSummary: {
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
        /** SeedlingTableSummary */
        SeedlingTableSummary: {
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
        /** SlotSummary */
        SlotSummary: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
            /** Shelf Code */
            shelf_code: string;
        };
        /**
         * SowNewBatchCreate
         * @description NURSERY-OPS-001: the operator-facing Sowing command -- one call
         *     creates exactly one Crop Batch and its one Sowing Event. No
         *     `workflow_id` field: the Workflow is auto-resolved server-side from
         *     the Seed Lot's crop/variety (see nursery_service._resolve_sowing_workflow).
         */
        SowNewBatchCreate: {
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            /**
             * Seed Lot Id
             * Format: uuid
             */
            seed_lot_id: string;
            /**
             * Seeding Station Id
             * Format: uuid
             */
            seeding_station_id: string;
            /** Seeding Machine Id */
            seeding_machine_id?: string | null;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /** Note */
            note?: string | null;
            /** Trays */
            trays: components["schemas"]["SowNewBatchTrayIn"][];
        };
        /** SowNewBatchTrayIn */
        SowNewBatchTrayIn: {
            /**
             * Carrier Id
             * Format: uuid
             */
            carrier_id: string;
            /** Sown Site Count */
            sown_site_count: number;
            /** Seeds Sown */
            seeds_sown: number;
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
            sown_site_count: number | null;
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
            seeding_station?: components["schemas"]["SeedingStationSummary"] | null;
            seeding_machine?: components["schemas"]["SeedingMachineSummary"] | null;
            /** Lines */
            lines: components["schemas"]["SowingEventLineRead"][];
            /**
             * Total Seeds Sown
             * @default 0
             */
            total_seeds_sown: number;
        };
        /**
         * SowingOrigin
         * @description One provable seed/sowing origin reachable from a batch's own
         *     derivation ancestry. A batch may have more than one (a future merge of
         *     batches sown on different dates) -- never collapsed to a guess.
         */
        SowingOrigin: {
            /**
             * Source Batch Id
             * Format: uuid
             */
            source_batch_id: string;
            /** Source Batch Code */
            source_batch_code: string;
            /**
             * Sowing Event Id
             * Format: uuid
             */
            sowing_event_id: string;
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
            /**
             * Seed Lot Id
             * Format: uuid
             */
            seed_lot_id: string;
            /** Seed Lot Code */
            seed_lot_code: string;
        };
        /** SpanSetupConfig */
        SpanSetupConfig: {
            /** Code */
            code: string;
            tables?: components["schemas"]["TableGeneratorConfig"] | null;
            gutters?: components["schemas"]["GutterGeneratorConfig"] | null;
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
        /**
         * StructureGerminationChamberNode
         * @description NURSERY-OPS-002A: `trolley_capacity` is the Chamber's configured
         *     number-of-Trolleys capacity (NULL means the DOMAIN-FARM-002 default of
         *     1, exclusive) -- never a tray/seed/plant quantity.
         */
        StructureGerminationChamberNode: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
            /** Trolley Capacity */
            trolley_capacity?: number | null;
        };
        /** StructureGutterNode */
        StructureGutterNode: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Code */
            code: string;
            /** Bag Position Count */
            bag_position_count: number;
        };
        /** StructureNurseryTableGroup */
        StructureNurseryTableGroup: {
            /** Area Id */
            area_id: string | null;
            /** Tables */
            tables: components["schemas"]["StructureTableNode"][];
        };
        /**
         * StructureSectionNode
         * @description FARM-SETUP-001.1: Seeding Station / Germination Chamber -- a single
         *     section directly under the Nursery Greenhouse, not a generated group.
         */
        StructureSectionNode: {
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
        /** StructureSpanNode */
        StructureSpanNode: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Code */
            code: string;
            /** Tables */
            tables: components["schemas"]["StructureTableNode"][];
        };
        /** StructureTableNode */
        StructureTableNode: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Code */
            code: string;
            /** Capacity */
            capacity: number | null;
        };
        /** StructureVinesSpanNode */
        StructureVinesSpanNode: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Code */
            code: string;
            /** Gutters */
            gutters: components["schemas"]["StructureGutterNode"][];
        };
        /** StructureVinesZoneNode */
        StructureVinesZoneNode: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Code */
            code: string;
            /** Spans */
            spans: components["schemas"]["StructureVinesSpanNode"][];
        };
        /** StructureZoneNode */
        StructureZoneNode: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Code */
            code: string;
            /** Spans */
            spans: components["schemas"]["StructureSpanNode"][];
        };
        /** SubtreeOccupancyRead */
        SubtreeOccupancyRead: {
            /**
             * Root Location Id
             * Format: uuid
             */
            root_location_id: string;
            /** Aggregate Counts */
            aggregate_counts: components["schemas"]["LocationAggregateCount"][];
            /** Occupied Locations */
            occupied_locations: components["schemas"]["OccupiedLocation"][];
        };
        /**
         * TableGeneratorConfig
         * @description Generates N sibling table-like locations under one parent, in one
         *     `_bulk_generate_children_core` call -- code_prefix/start/end/pad_width
         *     exactly mirror the existing `LocationBulkChildrenCreate` shape.
         *     Numbering restarts naturally per parent simply because each parent gets
         *     its own generator config with its own `start` (see LOCATION_MODEL.md
         *     setup section) -- no separate "restart vs continue" flag is needed.
         */
        TableGeneratorConfig: {
            /** Code Prefix */
            code_prefix: string;
            /** Start */
            start: number;
            /** End */
            end: number;
            /** Pad Width */
            pad_width: number;
            /** Capacity */
            capacity?: number | null;
        };
        /**
         * TargetOccupantRead
         * @description Legacy singular read. `active_occupancy` is only ONE occupant for a
         *     capacity>1 target with several active occupancies (the earliest by
         *     effective_time) -- `active_occupancy_count` (DOMAIN-FARM-002.1, additive)
         *     makes that explicit rather than silently implying `active_occupancy` is
         *     the complete state. A caller must check `active_occupancy_count > 1` (or
         *     just always prefer `TargetOccupantsRead`/`active_occupancies` below) to
         *     know whether more occupants exist than are shown here.
         */
        TargetOccupantRead: {
            target: components["schemas"]["TargetRef"];
            active_occupancy: components["schemas"]["OccupancyRead"] | null;
            /** Active Occupancy Count */
            active_occupancy_count: number;
        };
        /**
         * TargetOccupantsRead
         * @description DOMAIN-FARM-002.1: the truthful, complete read -- every active
         *     occupancy for the target, not just one. For a truly exclusive
         *     (capacity<=1) target this is 0 or 1 entries, identical in substance to
         *     `TargetOccupantRead`.
         */
        TargetOccupantsRead: {
            target: components["schemas"]["TargetRef"];
            /** Active Occupancies */
            active_occupancies: components["schemas"]["OccupancyRead"][];
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
        /** TransplantCorrectionCreate */
        TransplantCorrectionCreate: {
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            /** Reason */
            reason: string;
            replacement?: components["schemas"]["TransplantCorrectionReplacementIn"] | null;
        };
        /** TransplantCorrectionRead */
        TransplantCorrectionRead: {
            target_event: components["schemas"]["TransplantEventRead"];
            /** Status */
            status: string;
            reversal_event: components["schemas"]["TransplantEventRead"];
            replacement_event: components["schemas"]["TransplantEventRead"] | null;
            /** Reason */
            reason: string;
        };
        /**
         * TransplantCorrectionReplacementIn
         * @description The normal biological Transplant payload representing the correct
         *     facts -- no `effective_time` (server-derived from the target being
         *     corrected) and no InterSalads/Movement fields (biology only).
         */
        TransplantCorrectionReplacementIn: {
            /** Note */
            note?: string | null;
            /** Source Lines */
            source_lines: components["schemas"]["TransplantSourceLineIn"][];
            /** Destination Lines */
            destination_lines: components["schemas"]["TransplantDestinationLineIn"][];
            /** Allocations */
            allocations: components["schemas"]["TransplantAllocationIn"][];
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
            /** Total Source Available Before */
            total_source_available_before: number;
            /** Total Destination Plant Count */
            total_destination_plant_count: number;
            /** Total Discarded Plant Count */
            total_discarded_plant_count: number;
            /** Total Remainder After */
            total_remainder_after: number;
        };
        /**
         * TransplantSourceLineIn
         * @description NURSERY-OPS-004A: the operator supplies only the transplant-boundary
         *     reconciliation facts for a source Tray -- never `source_plant_count`
         *     (the authoritative `source_available_before`) and never
         *     `discarded_plant_count` (the server-computed aggregate of the four
         *     categorized counts below). Both are always server-derived (section 5/12).
         */
        TransplantSourceLineIn: {
            /**
             * Source Assignment Id
             * Format: uuid
             */
            source_assignment_id: string;
            /**
             * Transplant Damage Count
             * @default 0
             */
            transplant_damage_count: number;
            /**
             * Qc Rejection Count
             * @default 0
             */
            qc_rejection_count: number;
            /**
             * Sample Count
             * @default 0
             */
            sample_count: number;
            /**
             * Other Loss Count
             * @default 0
             */
            other_loss_count: number;
            /** Other Loss Note */
            other_loss_note?: string | null;
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
            /** Source Available Before */
            source_available_before: number;
            /** Successful Transferred Count */
            successful_transferred_count: number;
            /** Transplant Damage Count */
            transplant_damage_count: number;
            /** Qc Rejection Count */
            qc_rejection_count: number;
            /** Sample Count */
            sample_count: number;
            /** Other Loss Count */
            other_loss_count: number;
            /** Other Loss Note */
            other_loss_note: string | null;
            /** Discarded Plant Count */
            discarded_plant_count: number;
            /** Remainder After */
            remainder_after: number;
            /**
             * Checkpoint Id
             * Format: uuid
             */
            checkpoint_id: string;
            /** Note */
            note: string | null;
        };
        /** TrayPlacementRead */
        TrayPlacementRead: {
            /**
             * Movement Id
             * Format: uuid
             */
            movement_id: string;
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            tray: components["schemas"]["CarrierSummary"];
            /** Batch Code */
            batch_code: string;
            /** Seeds Sown */
            seeds_sown: number;
            trolley: components["schemas"]["TrolleySummary"];
            slot: components["schemas"]["SlotSummary"];
            chamber: components["schemas"]["GerminationChamberSummary"];
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
        };
        /**
         * TrolleyLevelGeneratorConfig
         * @description Mirrors `AssetPositionsGenerate` exactly. `slots_per_shelf` is the
         *     number of Seed Trays each Level physically holds -- represented as one
         *     exclusive numbered slot per tray (the existing, only, occupancy-
         *     compatibility-proven target for a seed_tray carrier), not as a single
         *     high-capacity shelf row; `slot_capacity` stays NULL/1 accordingly
         *     unless the caller has a genuine reason to widen it.
         */
        TrolleyLevelGeneratorConfig: {
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
            /** Slot Capacity */
            slot_capacity?: number | null;
        };
        /** TrolleyPlacementRead */
        TrolleyPlacementRead: {
            /**
             * Movement Id
             * Format: uuid
             */
            movement_id: string;
            /**
             * Client Command Id
             * Format: uuid
             */
            client_command_id: string;
            trolley: components["schemas"]["TrolleySummary"];
            chamber: components["schemas"]["GerminationChamberSummary"];
            /**
             * Effective Time
             * Format: date-time
             */
            effective_time: string;
        };
        /** TrolleySetupConfig */
        TrolleySetupConfig: {
            /** Code */
            code: string;
            /** Name */
            name?: string | null;
            levels: components["schemas"]["TrolleyLevelGeneratorConfig"];
        };
        /** TrolleySlotAvailabilityRead */
        TrolleySlotAvailabilityRead: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
            /** Shelf Code */
            shelf_code: string;
            /** Occupied */
            occupied: boolean;
        };
        /** TrolleySummary */
        TrolleySummary: {
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
        /** VinesSetupConfig */
        VinesSetupConfig: {
            /** Zones */
            zones: components["schemas"]["ZoneSetupConfig"][];
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
        /** ZoneSetupConfig */
        ZoneSetupConfig: {
            /** Code */
            code: string;
            /** Spans */
            spans: components["schemas"]["SpanSetupConfig"][];
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
    get_auth_me_auth_me_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-Dev-User-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
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
                    "application/json": components["schemas"]["AuthMeRead"];
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
    create_membership_memberships_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
    get_location_occupants_farms__farm_id__locations__location_id__occupants_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
                    "application/json": components["schemas"]["TargetOccupantsRead"];
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
    get_location_subtree_occupancy_farms__farm_id__locations__location_id__subtree_occupancy_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
                    "application/json": components["schemas"]["SubtreeOccupancyRead"];
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
    get_greenhouse_setup_overview_farms__farm_id__farm_setup_greenhouses_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
                    "application/json": components["schemas"]["GreenhouseOverviewItem"][];
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
    create_greenhouse_setup_farms__farm_id__farm_setup_greenhouses_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
            };
            path: {
                farm_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["GreenhouseSetupCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GreenhouseSetupResult"];
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
    get_greenhouse_structure_farms__farm_id__farm_setup_greenhouses__greenhouse_id__get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
            };
            path: {
                farm_id: string;
                greenhouse_id: string;
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
                    "application/json": components["schemas"]["GreenhouseStructureRead"];
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
    get_position_occupants_farms__farm_id__assets__asset_id__positions__position_id__occupants_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
                    "application/json": components["schemas"]["TargetOccupantsRead"];
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
    list_carrier_types_carrier_types_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
                    "application/json": components["schemas"]["CarrierTypeRead"][];
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
    list_carrier_specifications_carrier_specifications_get: {
        parameters: {
            query?: {
                carrier_type?: string | null;
                status?: string | null;
            };
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
                    "application/json": components["schemas"]["CarrierSpecificationRead"][];
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
    create_carrier_specification_carrier_specifications_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CarrierSpecificationCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CarrierSpecificationRead"];
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
    get_carrier_specification_carrier_specifications__specification_id__get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
            };
            path: {
                specification_id: string;
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
                    "application/json": components["schemas"]["CarrierSpecificationRead"];
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
    update_carrier_specification_carrier_specifications__specification_id__update_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
            };
            path: {
                specification_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CarrierSpecificationUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CarrierSpecificationRead"];
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
    deactivate_carrier_specification_carrier_specifications__specification_id__deactivate_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
            };
            path: {
                specification_id: string;
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
                    "application/json": components["schemas"]["CarrierSpecificationRead"];
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
    reactivate_carrier_specification_carrier_specifications__specification_id__reactivate_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
            };
            path: {
                specification_id: string;
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
                    "application/json": components["schemas"]["CarrierSpecificationRead"];
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
    get_crop_batches_operational_summary_farms__farm_id__crop_batches_operational_summary_get: {
        parameters: {
            query?: {
                state?: "active" | "all";
            };
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
                    "application/json": components["schemas"]["BatchOperationalContext"][];
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
    get_crop_batch_operational_context_farms__farm_id__crop_batches__batch_id__operational_context_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
                    "application/json": components["schemas"]["BatchOperationalContext"];
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
    list_batches_for_seed_lot_farms__farm_id__seed_lots__seed_lot_id__crop_batches_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
                    "application/json": components["schemas"]["SeedLotBatchSummary"][];
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
    sow_new_batch_farms__farm_id__nursery_sowings_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
            };
            path: {
                farm_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SowNewBatchCreate"];
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
    list_available_seed_trays_farms__farm_id__nursery_seed_trays_available_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
                    "application/json": components["schemas"]["AvailableSeedTrayRead"][];
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
    place_trolley_farms__farm_id__germination_trolley_placements_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
            };
            path: {
                farm_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PlaceTrolleyCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TrolleyPlacementRead"];
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
    place_tray_farms__farm_id__germination_tray_placements_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
            };
            path: {
                farm_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PlaceTrayCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TrayPlacementRead"];
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
    list_available_chambers_farms__farm_id__germination_chambers_available_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
                    "application/json": components["schemas"]["GerminationChamberAvailabilityRead"][];
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
    list_available_trolleys_farms__farm_id__germination_trolleys_available_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
                    "application/json": components["schemas"]["AvailableTrolleyRead"][];
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
    list_trolley_slots_farms__farm_id__germination_trolleys__trolley_id__slots_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
            };
            path: {
                farm_id: string;
                trolley_id: string;
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
                    "application/json": components["schemas"]["TrolleySlotAvailabilityRead"][];
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
    list_germination_trays_farms__farm_id__germination_trays_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
                    "application/json": components["schemas"]["GerminationTrayRead"][];
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
    list_germination_outcomes_farms__farm_id__crop_batches__batch_id__germination_outcomes_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
                    "application/json": components["schemas"]["GerminationOutcomeSnapshotRead"][];
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
    record_germination_outcomes_farms__farm_id__crop_batches__batch_id__germination_outcomes_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
            };
            path: {
                farm_id: string;
                batch_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["GerminationOutcomeCommandCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GerminationOutcomeCommandRead"];
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
    get_current_germination_outcomes_farms__farm_id__crop_batches__batch_id__germination_outcomes_current_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
                    "application/json": components["schemas"]["GerminationOutcomeBatchAggregateRead"];
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
    record_seedling_entry_farms__farm_id__nursery_seedling_entries_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
            };
            path: {
                farm_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SeedlingEntryCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SeedlingEntryRead"];
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
    list_available_seedling_tables_farms__farm_id__nursery_seedling_tables_available_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
                    "application/json": components["schemas"]["AvailableSeedlingTableRead"][];
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
    list_seedling_candidate_trays_farms__farm_id__nursery_seedling_trays_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
                    "application/json": components["schemas"]["SeedlingCandidateTrayRead"][];
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
    get_seedling_disposition_history_farms__farm_id__nursery_seedling_dispositions_get: {
        parameters: {
            query: {
                seedling_entry_id: string;
            };
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
                    "application/json": components["schemas"]["SeedlingDispositionHistoryRead"];
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
    record_seedling_disposition_farms__farm_id__nursery_seedling_dispositions_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
            };
            path: {
                farm_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RecordSeedlingDispositionCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SeedlingDispositionRecordResult"];
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
    correct_seedling_disposition_farms__farm_id__nursery_seedling_dispositions__event_id__correct_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
            };
            path: {
                farm_id: string;
                event_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CorrectSeedlingDispositionCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SeedlingDispositionCorrectResult"];
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
    list_seedling_disposition_reasons_farms__farm_id__nursery_seedling_disposition_reasons_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
                    "application/json": components["schemas"]["SeedlingDispositionReasonRead"][];
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
    list_seedling_biological_trays_farms__farm_id__nursery_seedling_biological_trays_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
                    "application/json": components["schemas"]["SeedlingBiologicalTrayRead"][];
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
    correct_transplant_farms__farm_id__crop_batches__batch_id__transplants__event_id__correct_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
            };
            path: {
                farm_id: string;
                batch_id: string;
                event_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TransplantCorrectionCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TransplantCorrectionRead"];
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
    record_intersalads_transplant_farms__farm_id__crop_batches__batch_id__intersalads_transplants_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
            };
            path: {
                farm_id: string;
                batch_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["IntersaladsTransplantCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["IntersaladsTransplantRead"];
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
    list_available_intersalads_plates_farms__farm_id__nursery_intersalads_available_plates_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
                    "application/json": components["schemas"]["AvailableNurseryCultivationPlateRead"][];
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
    record_leafy_production_transfer_farms__farm_id__crop_batches__batch_id__leafy_production_transfers_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
            };
            path: {
                farm_id: string;
                batch_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LeafyProductionTransferCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LeafyProductionTransferRead"];
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
    list_available_leafy_production_sources_farms__farm_id__leafy_production_available_sources_get: {
        parameters: {
            query?: {
                batch_id?: string | null;
            };
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
                    "application/json": components["schemas"]["AvailableLeafyProductionSourceRead"][];
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
    list_available_production_plates_farms__farm_id__leafy_production_available_plates_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
                    "application/json": components["schemas"]["AvailableProductionCultivationPlateRead"][];
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
    list_production_disposition_history_farms__farm_id__leafy_production_dispositions_get: {
        parameters: {
            query?: {
                batch_carrier_assignment_id?: string | null;
                batch_id?: string | null;
            };
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
                    "application/json": components["schemas"]["ProductionDispositionHistoryRead"][];
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
    record_production_disposition_farms__farm_id__leafy_production_dispositions_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
            };
            path: {
                farm_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RecordProductionDispositionCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProductionDispositionRecordResult"];
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
    correct_production_disposition_farms__farm_id__leafy_production_dispositions__event_id__correct_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
            };
            path: {
                farm_id: string;
                event_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CorrectProductionDispositionCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProductionDispositionCorrectResult"];
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
    list_active_production_plates_farms__farm_id__leafy_production_active_plates_get: {
        parameters: {
            query?: {
                batch_id?: string | null;
            };
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
                    "application/json": components["schemas"]["ActiveProductionPlateRead"][];
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
    list_harvestable_plates_farms__farm_id__leafy_production_harvestable_plates_get: {
        parameters: {
            query?: {
                batch_id?: string | null;
            };
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
                    "application/json": components["schemas"]["HarvestablePlateRead"][];
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
    list_leafy_harvests_farms__farm_id__leafy_production_harvests_get: {
        parameters: {
            query?: {
                batch_id?: string | null;
            };
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
                    "application/json": components["schemas"]["LeafyHarvestEventRead"][];
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
    record_leafy_harvest_farms__farm_id__leafy_production_harvests_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
            };
            path: {
                farm_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RecordLeafyHarvestCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LeafyHarvestEventRead"];
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
    get_leafy_harvest_farms__farm_id__leafy_production_harvests__harvest_event_id__get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
            };
            path: {
                farm_id: string;
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
                    "application/json": components["schemas"]["LeafyHarvestEventRead"];
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
    correct_leafy_harvest_source_line_farms__farm_id__leafy_production_harvests__harvest_event_id__source_lines__harvest_source_line_id__correct_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
            };
            path: {
                farm_id: string;
                harvest_event_id: string;
                harvest_source_line_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CorrectLeafyHarvestSourceLineCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LeafyHarvestEventRead"];
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
            header?: {
                authorization?: string | null;
                "X-CMP-Tenant-Id"?: string | null;
                "X-Dev-Tenant-Id"?: string | null;
                "X-Dev-User-Id"?: string | null;
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
