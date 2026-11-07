-- Generated opt-in existing-clip native controller rehearsal; not artist export acceptance.
return {
    ["profiles"] = {
        ["native-controller-rehearsal-v1"] = {
            ["auxiliary_events"] = {
                ["enable"] = true,
            },
            ["bone_names"] = {"root_point", "j_hips", "j_whip_parent", "j_whip_dynamic", "j_tail1", "j_tail1_scale", "j_tail2", "j_tail3", "j_tail4", "j_tail5", "j_tail6", "j_spine", "j_spine_scale", "j_spine1", "j_rightshoulder", "j_rightarm", "j_rightarm_scale", "j_rightforearm", "j_righthand", "j_rightweaponattach", "j_rightweaponcomponent9", "j_rightweaponcomponent8", "j_rightweaponcomponent7", "j_rightweaponcomponent6", "j_rightweaponcomponent5", "j_rightweaponcomponent4", "j_rightweaponcomponent3", "j_rightweaponcomponent2", "j_rightweaponcomponent10", "j_rightweaponcomponent1", "j_rightinhandthumb", "j_righthandthumb1", "j_righthandthumb2", "j_righthandring1", "j_righthandring2", "j_righthandring3", "j_righthandpinky1", "j_righthandpinky2", "j_righthandpinky3", "j_righthandmiddle1", "j_righthandmiddle2", "j_righthandmiddle3", "j_righthandindex1", "j_righthandindex2", "j_righthandindex3", "j_rightforearmroll", "j_neck", "j_necklace_01_parent", "j_necklace_01_dynamic", "j_necklace_02_parent", "j_necklace_02_dynamic", "j_neck_1", "j_head", "j_righteyelidtop", "j_righteyelidbottom", "j_righteyebrow3", "j_righteyebrow2", "j_righteyebrow1", "j_rightear", "j_nose", "j_lip_upright", "j_lip_upleft", "j_lip_right", "j_lip_left", "j_lefteyelidtop", "j_lefteyelidbottom", "j_lefteyebrow3", "j_lefteyebrow2", "j_lefteyebrow1", "j_leftear", "j_jaw", "j_lip_downright", "j_lip_downleft", "j_face_cloth_right_01_parent", "j_face_cloth_right_01_dynamic", "j_face_cloth_right_02_parent", "j_face_cloth_right_02_dynamic", "j_face_cloth_left_01_parent", "j_face_cloth_left_01_dynamic", "j_face_cloth_left_02_parent", "j_face_cloth_left_02_dynamic", "j_loot_sack", "j_loot_sack_component7", "j_loot_sack_component6", "j_loot_sack_component5", "j_loot_sack_component4", "j_loot_sack_component3", "j_loot_sack_component2", "j_loot_sack_component1", "j_leftshoulder", "j_leftarm", "j_leftarm_scale", "j_leftforearm", "j_lefthand", "j_leftweaponattach", "j_leftweaponcomponent9", "j_leftweaponcomponent8", "j_leftweaponcomponent7", "j_leftweaponcomponent6", "j_leftweaponcomponent5", "j_leftweaponcomponent4", "j_leftweaponcomponent3", "j_leftweaponcomponent2", "j_leftweaponcomponent10", "j_leftweaponcomponent1", "j_leftinhandthumb", "j_lefthandthumb1", "j_lefthandthumb2", "j_lefthandring1", "j_lefthandring2", "j_lefthandring3", "j_lefthandpinky1", "j_lefthandpinky2", "j_lefthandpinky3", "j_lefthandmiddle1", "j_lefthandmiddle2", "j_lefthandmiddle3", "j_lefthandindex1", "j_lefthandindex2", "j_lefthandindex3", "j_leftforearmroll", "j_backpack_parent", "j_backpack", "j_skull_parent", "j_skull_dynamic", "j_rightupleg", "j_rightupleg_scale", "j_rightleg", "j_rightfoot", "j_righttoebase", "j_rightinfootindex", "j_leftupleg", "j_leftupleg_scale", "j_leftleg", "j_leftfoot", "j_lefttoebase", "j_leftinfootindex", "aim_target"},
            ["cross_owner_transition_policy"] = "snapshot-blend-v1",
            ["default_state"] = "base/idle",
            ["manifest_id"] = "83332731d96c0c5a276189715ded6c4e45f7c3e14c8801a75a9d5feb9b8ee24d",
            ["max_blend_time"] = 0.25,
            ["native_rehearsal_only"] = true,
            ["sampler_state_machine"] = "units/warlock_bombardier/warlock_bombardier_3p/presentation_sampler",
            ["states"] = {
                ["base/death"] = {
                    ["clip"] = "units/warlock_bombardier/anims/death_shot",
                    ["loop_animation"] = false,
                    ["owner"] = "legacy",
                    ["speed"] = "measured",
                    ["speed_expression"] = "1",
                    ["transitions"] = {
                    },
                    ["visible_aim"] = false,
                },
                ["base/idle"] = {
                    ["aim_policy"] = "authored",
                    ["clip"] = "units/warlock_bombardier/anims/combat_idle",
                    ["loop_animation"] = true,
                    ["owner"] = "authored",
                    ["speed"] = "authored",
                    ["speed_expression"] = "1",
                    ["transitions"] = {
                        ["attack_shoot_align"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/shoot_start",
                        },
                        ["attack_shoot_loop"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/shoot_loop",
                        },
                        ["attack_shoot_start"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/shoot_loop",
                        },
                        ["death"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/death",
                        },
                        ["hit_reaction"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/stagger_fwd",
                        },
                        ["idle"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/idle",
                        },
                        ["move_fwd"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/walk",
                        },
                        ["move_fwd_run"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/run",
                        },
                        ["ragdoll"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/death",
                        },
                        ["reload_loop"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/reload_loop",
                        },
                        ["reload_start"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/reload_start",
                        },
                        ["stagger_bwd"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/stagger_bwd",
                        },
                        ["wind_up_loop"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/wind_up_loop",
                        },
                        ["wind_up_start"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/wind_up_start",
                        },
                    },
                    ["visible_aim"] = false,
                },
                ["base/reload_loop"] = {
                    ["clip"] = "units/warlock_bombardier/anims/combat_reload_loop",
                    ["loop_animation"] = true,
                    ["owner"] = "legacy",
                    ["speed"] = "measured",
                    ["speed_expression"] = "1",
                    ["transitions"] = {
                        ["attack_shoot_align"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/shoot_start",
                        },
                        ["attack_shoot_loop"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/shoot_loop",
                        },
                        ["attack_shoot_start"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/shoot_loop",
                        },
                        ["death"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/death",
                        },
                        ["hit_reaction"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/stagger_fwd",
                        },
                        ["idle"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/idle",
                        },
                        ["move_fwd"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/walk",
                        },
                        ["move_fwd_run"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/run",
                        },
                        ["ragdoll"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/death",
                        },
                        ["reload_loop"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/reload_loop",
                        },
                        ["reload_start"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/reload_start",
                        },
                        ["stagger_bwd"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/stagger_bwd",
                        },
                        ["wind_up_loop"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/wind_up_loop",
                        },
                        ["wind_up_start"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/wind_up_start",
                        },
                    },
                    ["visible_aim"] = true,
                },
                ["base/reload_start"] = {
                    ["clip"] = "units/warlock_bombardier/anims/combat_reload_start",
                    ["loop_animation"] = false,
                    ["owner"] = "legacy",
                    ["speed"] = "measured",
                    ["speed_expression"] = "1",
                    ["transitions"] = {
                        ["attack_shoot_align"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/shoot_start",
                        },
                        ["attack_shoot_loop"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/shoot_loop",
                        },
                        ["attack_shoot_start"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/shoot_loop",
                        },
                        ["death"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/death",
                        },
                        ["hit_reaction"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/stagger_fwd",
                        },
                        ["idle"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/idle",
                        },
                        ["move_fwd"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/walk",
                        },
                        ["move_fwd_run"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/run",
                        },
                        ["ragdoll"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/death",
                        },
                        ["reload_loop"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/reload_loop",
                        },
                        ["reload_start"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/reload_start",
                        },
                        ["stagger_bwd"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/stagger_bwd",
                        },
                        ["wind_up_loop"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/wind_up_loop",
                        },
                        ["wind_up_start"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/wind_up_start",
                        },
                    },
                    ["visible_aim"] = true,
                },
                ["base/run"] = {
                    ["clip"] = "units/warlock_bombardier/anims/combat_run",
                    ["loop_animation"] = true,
                    ["owner"] = "legacy",
                    ["speed"] = "measured",
                    ["speed_expression"] = "warlock_move_speed / 4",
                    ["transitions"] = {
                        ["attack_shoot_align"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/shoot_start",
                        },
                        ["attack_shoot_loop"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/shoot_loop",
                        },
                        ["attack_shoot_start"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/shoot_loop",
                        },
                        ["death"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/death",
                        },
                        ["hit_reaction"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/stagger_fwd",
                        },
                        ["idle"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/idle",
                        },
                        ["move_fwd"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/walk",
                        },
                        ["move_fwd_run"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/run",
                        },
                        ["ragdoll"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/death",
                        },
                        ["reload_loop"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/reload_loop",
                        },
                        ["reload_start"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/reload_start",
                        },
                        ["stagger_bwd"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/stagger_bwd",
                        },
                        ["wind_up_loop"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/wind_up_loop",
                        },
                        ["wind_up_start"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/wind_up_start",
                        },
                    },
                    ["visible_aim"] = true,
                },
                ["base/shoot_loop"] = {
                    ["clip"] = "units/warlock_bombardier/anims/combat_shoot_loop",
                    ["loop_animation"] = true,
                    ["owner"] = "legacy",
                    ["speed"] = "measured",
                    ["speed_expression"] = "1",
                    ["transitions"] = {
                        ["attack_shoot_align"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/shoot_start",
                        },
                        ["attack_shoot_loop"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/shoot_loop",
                        },
                        ["attack_shoot_start"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/shoot_loop",
                        },
                        ["death"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/death",
                        },
                        ["hit_reaction"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/stagger_fwd",
                        },
                        ["idle"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/idle",
                        },
                        ["move_fwd"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/walk",
                        },
                        ["move_fwd_run"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/run",
                        },
                        ["ragdoll"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/death",
                        },
                        ["reload_loop"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/reload_loop",
                        },
                        ["reload_start"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/reload_start",
                        },
                        ["stagger_bwd"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/stagger_bwd",
                        },
                        ["wind_up_loop"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/wind_up_loop",
                        },
                        ["wind_up_start"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/wind_up_start",
                        },
                    },
                    ["visible_aim"] = true,
                },
                ["base/shoot_start"] = {
                    ["clip"] = "units/warlock_bombardier/anims/combat_shoot_start",
                    ["loop_animation"] = false,
                    ["owner"] = "legacy",
                    ["speed"] = "measured",
                    ["speed_expression"] = "1",
                    ["transitions"] = {
                        ["attack_shoot_align"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/shoot_start",
                        },
                        ["attack_shoot_loop"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/shoot_loop",
                        },
                        ["attack_shoot_start"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/shoot_loop",
                        },
                        ["death"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/death",
                        },
                        ["hit_reaction"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/stagger_fwd",
                        },
                        ["idle"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/idle",
                        },
                        ["move_fwd"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/walk",
                        },
                        ["move_fwd_run"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/run",
                        },
                        ["ragdoll"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/death",
                        },
                        ["reload_loop"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/reload_loop",
                        },
                        ["reload_start"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/reload_start",
                        },
                        ["stagger_bwd"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/stagger_bwd",
                        },
                        ["wind_up_loop"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/wind_up_loop",
                        },
                        ["wind_up_start"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/wind_up_start",
                        },
                    },
                    ["visible_aim"] = true,
                },
                ["base/stagger_bwd"] = {
                    ["clip"] = "units/warlock_bombardier/anims/stagger_bwd",
                    ["loop_animation"] = false,
                    ["owner"] = "legacy",
                    ["speed"] = "measured",
                    ["speed_expression"] = "1",
                    ["transitions"] = {
                        ["attack_shoot_align"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/shoot_start",
                        },
                        ["attack_shoot_loop"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/shoot_loop",
                        },
                        ["attack_shoot_start"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/shoot_loop",
                        },
                        ["death"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/death",
                        },
                        ["hit_reaction"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/stagger_fwd",
                        },
                        ["idle"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/idle",
                        },
                        ["move_fwd"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/walk",
                        },
                        ["move_fwd_run"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/run",
                        },
                        ["ragdoll"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/death",
                        },
                        ["reload_loop"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/reload_loop",
                        },
                        ["reload_start"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/reload_start",
                        },
                        ["stagger_bwd"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/stagger_bwd",
                        },
                        ["wind_up_loop"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/wind_up_loop",
                        },
                        ["wind_up_start"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/wind_up_start",
                        },
                    },
                    ["visible_aim"] = false,
                },
                ["base/stagger_fwd"] = {
                    ["clip"] = "units/warlock_bombardier/anims/stagger_fwd",
                    ["loop_animation"] = false,
                    ["owner"] = "legacy",
                    ["speed"] = "measured",
                    ["speed_expression"] = "1",
                    ["transitions"] = {
                        ["attack_shoot_align"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/shoot_start",
                        },
                        ["attack_shoot_loop"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/shoot_loop",
                        },
                        ["attack_shoot_start"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/shoot_loop",
                        },
                        ["death"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/death",
                        },
                        ["hit_reaction"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/stagger_fwd",
                        },
                        ["idle"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/idle",
                        },
                        ["move_fwd"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/walk",
                        },
                        ["move_fwd_run"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/run",
                        },
                        ["ragdoll"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/death",
                        },
                        ["reload_loop"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/reload_loop",
                        },
                        ["reload_start"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/reload_start",
                        },
                        ["stagger_bwd"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/stagger_bwd",
                        },
                        ["wind_up_loop"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/wind_up_loop",
                        },
                        ["wind_up_start"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/wind_up_start",
                        },
                    },
                    ["visible_aim"] = false,
                },
                ["base/walk"] = {
                    ["clip"] = "units/warlock_bombardier/anims/combat_walk",
                    ["loop_animation"] = true,
                    ["owner"] = "legacy",
                    ["speed"] = "measured",
                    ["speed_expression"] = "warlock_move_speed / 1.9",
                    ["transitions"] = {
                        ["attack_shoot_align"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/shoot_start",
                        },
                        ["attack_shoot_loop"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/shoot_loop",
                        },
                        ["attack_shoot_start"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/shoot_loop",
                        },
                        ["death"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/death",
                        },
                        ["hit_reaction"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/stagger_fwd",
                        },
                        ["idle"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/idle",
                        },
                        ["move_fwd"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/walk",
                        },
                        ["move_fwd_run"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/run",
                        },
                        ["ragdoll"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/death",
                        },
                        ["reload_loop"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/reload_loop",
                        },
                        ["reload_start"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/reload_start",
                        },
                        ["stagger_bwd"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/stagger_bwd",
                        },
                        ["wind_up_loop"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/wind_up_loop",
                        },
                        ["wind_up_start"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/wind_up_start",
                        },
                    },
                    ["visible_aim"] = true,
                },
                ["base/wind_up_loop"] = {
                    ["clip"] = "units/warlock_bombardier/anims/combat_wind_up_loop",
                    ["loop_animation"] = true,
                    ["owner"] = "legacy",
                    ["speed"] = "measured",
                    ["speed_expression"] = "1",
                    ["transitions"] = {
                        ["attack_shoot_align"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/shoot_start",
                        },
                        ["attack_shoot_loop"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/shoot_loop",
                        },
                        ["attack_shoot_start"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/shoot_loop",
                        },
                        ["death"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/death",
                        },
                        ["hit_reaction"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/stagger_fwd",
                        },
                        ["idle"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/idle",
                        },
                        ["move_fwd"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/walk",
                        },
                        ["move_fwd_run"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/run",
                        },
                        ["ragdoll"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/death",
                        },
                        ["reload_loop"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/reload_loop",
                        },
                        ["reload_start"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/reload_start",
                        },
                        ["stagger_bwd"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/stagger_bwd",
                        },
                        ["wind_up_loop"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/wind_up_loop",
                        },
                        ["wind_up_start"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/wind_up_start",
                        },
                    },
                    ["visible_aim"] = true,
                },
                ["base/wind_up_start"] = {
                    ["clip"] = "units/warlock_bombardier/anims/combat_wind_up_start",
                    ["loop_animation"] = false,
                    ["owner"] = "legacy",
                    ["speed"] = "measured",
                    ["speed_expression"] = "1",
                    ["transitions"] = {
                        ["attack_shoot_align"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/shoot_start",
                        },
                        ["attack_shoot_loop"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/shoot_loop",
                        },
                        ["attack_shoot_start"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/shoot_loop",
                        },
                        ["death"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/death",
                        },
                        ["hit_reaction"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/stagger_fwd",
                        },
                        ["idle"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/idle",
                        },
                        ["move_fwd"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/walk",
                        },
                        ["move_fwd_run"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/run",
                        },
                        ["ragdoll"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/death",
                        },
                        ["reload_loop"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/reload_loop",
                        },
                        ["reload_start"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/reload_start",
                        },
                        ["stagger_bwd"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/stagger_bwd",
                        },
                        ["wind_up_loop"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/wind_up_loop",
                        },
                        ["wind_up_start"] = {
                            ["blend_time"] = 0.25,
                            ["to"] = "base/wind_up_start",
                        },
                    },
                    ["visible_aim"] = true,
                },
            },
            ["unit"] = "units/warlock_bombardier/warlock_bombardier_3p",
            ["validation"] = {
                ["artist_export_acceptance"] = false,
                ["localized_garment_acceptance"] = false,
                ["sampler_state_machine_sha256"] = "41ac4471a2276e08aae84e9687b4e2921930ab997f18d06234a2fa79fbf2c49a",
                ["scope"] = "existing-stock-clip-native-controller-rehearsal",
                ["source_files_sha256"] = {
                    ["resource_packages/doomrocket/doomrocket.package"] = "4a2a2883798059729dceb65669f3a2e92459eca9b2bdc46042d0eed97c4792d7",
                    ["units/warlock_bombardier/anims/combat_idle.animation"] = "92f1cbcb404981bb2fba961023ea38228f6d3a05a141e4264ae143a94ed45ec6",
                    ["units/warlock_bombardier/anims/combat_idle.fbx"] = "63763fed076b81eafadfa2a5675705ee20cd6dea43e0c7747dffc8e1a91baf03",
                    ["units/warlock_bombardier/anims/combat_reload_loop.animation"] = "92f1cbcb404981bb2fba961023ea38228f6d3a05a141e4264ae143a94ed45ec6",
                    ["units/warlock_bombardier/anims/combat_reload_loop.fbx"] = "273885badf26e70aa0fbbc73363cdfe5fe572a2322eac907a729f7aecae4e76e",
                    ["units/warlock_bombardier/anims/combat_reload_start.animation"] = "92f1cbcb404981bb2fba961023ea38228f6d3a05a141e4264ae143a94ed45ec6",
                    ["units/warlock_bombardier/anims/combat_reload_start.fbx"] = "dc59322e1a9a4814b2816224a6edce908ceaa5021bb6cf9c69ac40a5669fdf0d",
                    ["units/warlock_bombardier/anims/combat_run.animation"] = "92f1cbcb404981bb2fba961023ea38228f6d3a05a141e4264ae143a94ed45ec6",
                    ["units/warlock_bombardier/anims/combat_run.fbx"] = "da2875eae58bcd8719fca4d4854b2fd2a3bfb2ab04efcdff0da5a87854f29125",
                    ["units/warlock_bombardier/anims/combat_run_start_fwd.animation"] = "92f1cbcb404981bb2fba961023ea38228f6d3a05a141e4264ae143a94ed45ec6",
                    ["units/warlock_bombardier/anims/combat_run_start_fwd.fbx"] = "d72f9342ff08d6a9d29311ba582e78c5d423994934d4e51e180c7e47939998bc",
                    ["units/warlock_bombardier/anims/combat_shoot_loop.animation"] = "92f1cbcb404981bb2fba961023ea38228f6d3a05a141e4264ae143a94ed45ec6",
                    ["units/warlock_bombardier/anims/combat_shoot_loop.fbx"] = "2601ebb2a0bc836702dfde393647b0703e3840048aef589ee73d37fb65b0799e",
                    ["units/warlock_bombardier/anims/combat_shoot_start.animation"] = "92f1cbcb404981bb2fba961023ea38228f6d3a05a141e4264ae143a94ed45ec6",
                    ["units/warlock_bombardier/anims/combat_shoot_start.fbx"] = "03b5b1a9d5ab8918228ac04eb82fa9548ccb4a0aa730e4e27d5d02b9a8838cb8",
                    ["units/warlock_bombardier/anims/combat_walk.animation"] = "92f1cbcb404981bb2fba961023ea38228f6d3a05a141e4264ae143a94ed45ec6",
                    ["units/warlock_bombardier/anims/combat_walk.fbx"] = "f5e3055f216497b7cc9af6420c1f4d48d5d9854fb92394a4aa59aa6377c4293e",
                    ["units/warlock_bombardier/anims/combat_wind_up_loop.animation"] = "92f1cbcb404981bb2fba961023ea38228f6d3a05a141e4264ae143a94ed45ec6",
                    ["units/warlock_bombardier/anims/combat_wind_up_loop.fbx"] = "3dad72ca64470421a1a2763e11e12dbb7c3be1da93b3f0e93c7cfb25a630322a",
                    ["units/warlock_bombardier/anims/combat_wind_up_start.animation"] = "92f1cbcb404981bb2fba961023ea38228f6d3a05a141e4264ae143a94ed45ec6",
                    ["units/warlock_bombardier/anims/combat_wind_up_start.fbx"] = "88a6cf88f88c28f1531ab76d2858e7a5a9de06829e1619488952dbdd62a83cb0",
                    ["units/warlock_bombardier/anims/death_shot.animation"] = "92f1cbcb404981bb2fba961023ea38228f6d3a05a141e4264ae143a94ed45ec6",
                    ["units/warlock_bombardier/anims/death_shot.fbx"] = "84e12bf715f9aee58eadaffc36ca260545ee68e7fcffde6087ef9157cd9add08",
                    ["units/warlock_bombardier/anims/stagger_bwd.animation"] = "92f1cbcb404981bb2fba961023ea38228f6d3a05a141e4264ae143a94ed45ec6",
                    ["units/warlock_bombardier/anims/stagger_bwd.fbx"] = "2f131537c72638de0c6a82f50965335804ce5651031516061e6cdbd7615ac385",
                    ["units/warlock_bombardier/anims/stagger_fwd.animation"] = "92f1cbcb404981bb2fba961023ea38228f6d3a05a141e4264ae143a94ed45ec6",
                    ["units/warlock_bombardier/anims/stagger_fwd.fbx"] = "b03d0006a38eaf0b4368ded67a749c6f40ac701df36b0b0cbe035640ef03db80",
                    ["units/warlock_bombardier/warlock_bombardier_3p.bones"] = "6e4eb323ba5a21db1e2f09f91d73cfa1e3234a03d7b183223f48ccd96c51a197",
                    ["units/warlock_bombardier/warlock_bombardier_3p.dcc_asset"] = "029e4e980f58906ceb0273cac1ff96e38f1127a00558e9c6e10417ea735eb609",
                    ["units/warlock_bombardier/warlock_bombardier_3p.fbx"] = "cb2eba0224d1eff044a30b1bf0269d1a10395e8db9244af5c011e5c0ba0bd0bc",
                    ["units/warlock_bombardier/warlock_bombardier_3p.state_machine"] = "963214ae1729444030dc24e8ec0e02949d1063b738c9f1c9a6c2deaa5f7836b3",
                    ["units/warlock_bombardier/warlock_bombardier_3p.unit"] = "501afcaae776658407208ce20fd8236a9d9f82b398939111ad62607c39b084b4",
                },
                ["visible_state_machine_sha256"] = "74a63e983370ecb921a57270b67252d2b075f160add6699416c141ae30ed2f7e",
            },
            ["visible_state_machine"] = "units/warlock_bombardier/warlock_bombardier_3p/native_controller_rehearsal",
            ["weapon_links"] = {{
                ["source"] = "j_leftweaponattach",
                ["target"] = 0,
                ["world_scale"] = {1, 1, 1},
            }, {
                ["source"] = "j_leftweaponcomponent1",
                ["target"] = "a_barrel",
                ["world_scale"] = {1, 1, 1},
            }, {
                ["source"] = "j_lefthand",
                ["target"] = "handle",
                ["world_scale"] = {1, 1, 1},
            }},
        },
    },
    ["schema"] = 1,
}
