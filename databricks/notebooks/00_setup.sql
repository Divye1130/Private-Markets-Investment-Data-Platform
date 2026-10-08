-- Databricks notebook source
-- Set a catalog/schema that your workspace permits. `main` is a common Unity Catalog default.
USE CATALOG main;
CREATE SCHEMA IF NOT EXISTS private_markets;
USE SCHEMA private_markets;

CREATE VOLUME IF NOT EXISTS raw_inputs;
CREATE VOLUME IF NOT EXISTS quarantine;
