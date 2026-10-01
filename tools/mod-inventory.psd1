@{
    Mods = @(
        @{
            Dir = 'doomrocket'; ModId = 'doomrocket'; WorkshopId = '3771657344';
            Visibility = 'public'; Stream = 'alpha'; Public = $true;
            Name = 'Warlock Engineer'; BundleAuthority = 'receipt';
            RootBundle = 'ac226cc769a897ae.mod_bundle';
            BuildArtifactExclusions = @(
                @{
                    Name = 'e7852992f40eb619.mod_bundle';
                    Sha256 = 'e1a04e500f8255ebedcaffb4e35e829adbd99ebf46c2b8b4cd89d26dca4735e2';
                    Reason = 'SDK tool-only BUNDLE=false LUT-generator sidecar emitted nondeterministically by clean Stingray builds (same policy as vermintide-2-tweaker)'
                }
            )
        }
    )
}
