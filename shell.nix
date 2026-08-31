{ pkgs ? import <nixpkgs> {} }:

with pkgs; pkgs.mkShell {
  buildInputs = [
    # AWS / EKS. awscli2 covers auth (kubeconfig uses `aws eks get-token` as an
    # exec plugin, no separate authenticator binary needed), IAM/S3 setup, and
    # pod-identity associations. eksctl for OIDC-provider / IRSA-role plumbing.
    awscli2
    eksctl

    kubectl
    kubernetes-helm


    jq

    # for the test program
    nodejs
    pnpm
    biome
    typescript-language-server
  ];
}
