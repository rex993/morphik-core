"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
import dynamic from "next/dynamic";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { AlertCircle, Share2, Plus, Network, Tag, Link, ArrowLeft } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Skeleton } from "@/components/ui/skeleton";

// Dynamically import ForceGraphComponent to avoid SSR issues
const ForceGraphComponent = dynamic(() => import("@/components/ForceGraphComponent"), {
  ssr: false,
});

// Define interfaces
interface Graph {
  id: string;
  name: string;
  entities: Entity[];
  relationships: Relationship[];
  metadata: Record<string, unknown>;
  document_ids: string[];
  filters?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  system_metadata?: {
    status?: string;
    [key: string]: unknown;
  };
}

interface Entity {
  id: string;
  label: string;
  type: string;
  properties: Record<string, unknown>;
  chunk_sources: Record<string, number[]>;
}

interface Relationship {
  id: string;
  type: string;
  source_id: string;
  target_id: string;
}

interface GraphSectionProps {
  apiBaseUrl: string;
  onSelectGraph?: (graphName: string | undefined) => void;
  onGraphCreate?: (graphName: string, numDocuments: number) => void;
  onGraphUpdate?: (graphName: string, numAdditionalDocuments: number) => void;
  authToken?: string | null;
}

// Map entity types to colors
const entityTypeColors: Record<string, string> = {
  person: "#4f46e5", // Indigo
  organization: "#06b6d4", // Cyan
  location: "#10b981", // Emerald
  date: "#f59e0b", // Amber
  concept: "#8b5cf6", // Violet
  event: "#ec4899", // Pink
  product: "#ef4444", // Red
  default: "#6b7280", // Gray
};

const POLL_INTERVAL_MS = 60000; // 1 minute

const GraphSection: React.FC<GraphSectionProps> = ({
  apiBaseUrl,
  onSelectGraph,
  onGraphCreate,
  onGraphUpdate,
  authToken,
}) => {
  // Create auth headers for API requests if auth token is available
  const createHeaders = useCallback(
    (contentType?: string): HeadersInit => {
      const headers: HeadersInit = {};

      if (authToken) {
        headers["Authorization"] = `Bearer ${authToken}`;
      }

      if (contentType) {
        headers["Content-Type"] = contentType;
      }

      return headers;
    },
    [authToken]
  );
  // State variables
  const [graphs, setGraphs] = useState<Graph[]>([]);
  const [selectedGraph, setSelectedGraph] = useState<Graph | null>(null);
  const [graphName, setGraphName] = useState("");
  const [graphDocuments, setGraphDocuments] = useState<string[]>([]);
  const [graphFilters, setGraphFilters] = useState("{}");
  const [additionalDocuments, setAdditionalDocuments] = useState<string[]>([]);
  const [additionalFilters, setAdditionalFilters] = useState("{}");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("list"); // 'list', 'details', 'update', 'visualize' (no longer a tab, but a state)
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [showNodeLabels, setShowNodeLabels] = useState(true);
  const [showLinkLabels, setShowLinkLabels] = useState(true);
  const [showVisualization, setShowVisualization] = useState(false);
  const [graphDimensions, setGraphDimensions] = useState({ width: 0, height: 0 });

  // Refs for graph visualization
  const graphContainerRef = useRef<HTMLDivElement>(null);
  // Removed graphInstance ref as it's not needed with the dynamic component

  // Prepare data for force-graph
  const prepareGraphData = useCallback((graph: Graph | null) => {
    if (!graph) return { nodes: [], links: [] };

    const nodes = graph.entities.map(entity => ({
      id: entity.id,
      label: entity.label,
      type: entity.type,
      properties: entity.properties,
      color: entityTypeColors[entity.type.toLowerCase()] || entityTypeColors.default,
    }));

    // Create a Set of all entity IDs for faster lookups
    const nodeIdSet = new Set(graph.entities.map(entity => entity.id));

    // Filter relationships to only include those where both source and target nodes exist
    const links = graph.relationships
      .filter(rel => nodeIdSet.has(rel.source_id) && nodeIdSet.has(rel.target_id))
      .map(rel => ({
        source: rel.source_id,
        target: rel.target_id,
        type: rel.type,
      }));

    return { nodes, links };
  }, []);

  // Removed initializeGraph function as it's no longer needed

  // Observe graph container size changes
  useEffect(() => {
    if (!showVisualization || !graphContainerRef.current) return;

    const resizeObserver = new ResizeObserver(entries => {
      for (const entry of entries) {
        setGraphDimensions({
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        });
      }
    });

    resizeObserver.observe(graphContainerRef.current);

    // Set initial size
    setGraphDimensions({
      width: graphContainerRef.current.clientWidth,
      height: graphContainerRef.current.clientHeight,
    });

    const currentGraphContainer = graphContainerRef.current; // Store ref value
    return () => {
      if (currentGraphContainer) {
        // Use stored value in cleanup
        resizeObserver.unobserve(currentGraphContainer);
      }
      resizeObserver.disconnect();
    };
  }, [showVisualization]); // Rerun when visualization becomes active/inactive

  // Fetch all graphs
  const fetchGraphs = useCallback(async () => {
    try {
      setLoading(true);
      const headers = createHeaders();
      const response = await fetch(`${apiBaseUrl}/graphs`, { headers });

      if (!response.ok) {
        throw new Error(`Failed to fetch graphs: ${response.statusText}`);
      }

      const data = await response.json();
      setGraphs(data);
    } catch (err: unknown) {
      const error = err as Error;
      setError(`Error fetching graphs: ${error.message}`);
      console.error("Error fetching graphs:", err);
    } finally {
      setLoading(false);
    }
  }, [apiBaseUrl, createHeaders]);

  // Fetch graphs on component mount
  useEffect(() => {
    fetchGraphs();
  }, [fetchGraphs]);

  // Fetch a specific graph
  const fetchGraph = async (graphName: string) => {
    try {
      setLoading(true);
      setError(null); // Clear previous errors
      const headers = createHeaders();
      const response = await fetch(`${apiBaseUrl}/graph/${encodeURIComponent(graphName)}`, {
        headers,
      });

      if (!response.ok) {
        throw new Error(`Failed to fetch graph: ${response.statusText}`);
      }

      const data = await response.json();
      setSelectedGraph(data);
      setActiveTab("details"); // Set tab to details view

      // Call the callback if provided
      if (onSelectGraph) {
        onSelectGraph(graphName);
      }

      return data;
    } catch (err: unknown) {
      const error = err as Error;
      setError(`Error fetching graph: ${error.message}`);
      console.error("Error fetching graph:", err);
      setSelectedGraph(null); // Reset selected graph on error
      setActiveTab("list"); // Go back to list view on error
      if (onSelectGraph) {
        onSelectGraph(undefined);
      }
      return null;
    } finally {
      setLoading(false);
    }
  };

  // Handle graph click
  const handleGraphClick = (graph: Graph) => {
    fetchGraph(graph.name);
  };

  // Create a new graph
  const handleCreateGraph = async () => {
    if (!graphName.trim()) {
      setError("Please enter a graph name");
      return;
    }

    try {
      setLoading(true);
      setError(null);

      // Parse filters
      let parsedFilters = {};
      try {
        parsedFilters = JSON.parse(graphFilters);
      } catch {
        throw new Error("Invalid JSON in filters field");
      }

      const headers = createHeaders("application/json");
      const response = await fetch(`${apiBaseUrl}/graph/create`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          name: graphName,
          filters: Object.keys(parsedFilters).length > 0 ? parsedFilters : undefined,
          documents: graphDocuments.length > 0 ? graphDocuments : undefined,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || `Failed to create graph: ${response.statusText}`);
      }

      const data = await response.json();
      setSelectedGraph(data);
      setActiveTab("details"); // Switch to details tab after creation

      // Invoke callback before refresh
      onGraphCreate?.(graphName, graphDocuments.length);

      // Refresh the graphs list
      await fetchGraphs();

      // Reset form
      setGraphName("");
      setGraphDocuments([]);
      setGraphFilters("{}");

      // Close dialog
      setShowCreateDialog(false);
    } catch (err: unknown) {
      const error = err as Error;
      setError(`Error creating graph: ${error.message}`);
      console.error("Error creating graph:", err);
      // Keep the dialog open on error so user can fix it
    } finally {
      setLoading(false);
    }
  };

  // Update an existing graph
  const handleUpdateGraph = async () => {
    if (!selectedGraph) {
      setError("No graph selected for update");
      return;
    }

    try {
      setLoading(true);
      setError(null);

      // Parse additional filters
      let parsedFilters = {};
      try {
        parsedFilters = JSON.parse(additionalFilters);
      } catch {
        throw new Error("Invalid JSON in additional filters field");
      }

      const headers = createHeaders("application/json");
      const response = await fetch(`${apiBaseUrl}/graph/${encodeURIComponent(selectedGraph.name)}/update`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          additional_filters: Object.keys(parsedFilters).length > 0 ? parsedFilters : undefined,
          additional_documents: additionalDocuments.length > 0 ? additionalDocuments : undefined,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || `Failed to update graph: ${response.statusText}`);
      }

      const data = await response.json();
      setSelectedGraph(data);
      setActiveTab("details"); // Update the selected graph data

      // Invoke callback before refresh
      onGraphUpdate?.(selectedGraph.name, additionalDocuments.length);

      // Refresh the graphs list
      await fetchGraphs();

      // Reset form
      setAdditionalDocuments([]);
      setAdditionalFilters("{}");

      // Switch back to details tab
      setActiveTab("details");
    } catch (err: unknown) {
      const error = err as Error;
      setError(`Error updating graph: ${error.message}`);
      console.error("Error updating graph:", err);
      // Keep the update form visible on error
    } finally {
      setLoading(false);
    }
  };

  // Removed useEffect that depended on initializeGraph

  // Poll for processing graphs
  useEffect(() => {
    // Start polling only if at least one graph is processing
    const hasProcessing = graphs.some(g => g.system_metadata?.status === "processing");

    if (!hasProcessing) return; // No need to poll

    const id = setInterval(async () => {
      await fetchGraphs();
      // Refresh selected graph if it is still processing
      if (selectedGraph?.system_metadata?.status === "processing") {
        await fetchGraph(selectedGraph.name);
      }
    }, POLL_INTERVAL_MS);

    return () => clearInterval(id);
  }, [graphs, selectedGraph, fetchGraphs]);

  // Conditional rendering based on visualization state
  if (showVisualization && selectedGraph) {
    return (
      <div className="fixed inset-0 z-50 flex flex-col bg-background">
        {/* Visualization header */}
        <div className="flex items-center justify-between border-b p-4">
          <div className="flex items-center gap-4">
            <Button
              variant="ghost"
              size="icon"
              className="rounded-full hover:bg-muted/50"
              onClick={() => setShowVisualization(false)}
            >
              <ArrowLeft size={18} />
            </Button>
            <div className="flex items-center">
              <Network className="mr-2 h-6 w-6 text-primary" />
              <h2 className="text-lg font-medium">{selectedGraph.name} Visualization</h2>
            </div>
          </div>

          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <Tag className="h-4 w-4" />
              <Label htmlFor="show-node-labels" className="cursor-pointer text-sm">
                Nodes
              </Label>
              <Switch id="show-node-labels" checked={showNodeLabels} onCheckedChange={setShowNodeLabels} />
            </div>
            <div className="flex items-center gap-2">
              <Link className="h-4 w-4" />
              <Label htmlFor="show-link-labels" className="cursor-pointer text-sm">
                Relationships
              </Label>
              <Switch id="show-link-labels" checked={showLinkLabels} onCheckedChange={setShowLinkLabels} />
            </div>
          </div>
        </div>

        {/* Graph visualization container */}
        <div ref={graphContainerRef} className="relative flex-1">
          {graphDimensions.width > 0 && graphDimensions.height > 0 && (
            <ForceGraphComponent
              data={prepareGraphData(selectedGraph)}
              width={graphDimensions.width}
              height={graphDimensions.height}
              showNodeLabels={showNodeLabels}
              showLinkLabels={showLinkLabels}
            />
          )}
        </div>
      </div>
    );
  }

  // Default view (List or Details/Update)
  return (
    <div className="flex h-full flex-1 flex-col p-4">
      <div className="flex flex-1 flex-col">
        {/* Graph List View */}
        {activeTab === "list" && (
          <div className="mb-6">
            <div className="mb-4 flex items-center justify-end">
              {" "}
              {/* Removed justify-between and empty div */}
              <Dialog open={showCreateDialog} onOpenChange={setShowCreateDialog}>
                <DialogTrigger asChild>
                  <Button variant="outline" size="sm">
                    <Plus className="mr-2 h-4 w-4" /> New Graph
                  </Button>
                </DialogTrigger>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle className="flex items-center">
                      <Plus className="mr-2 h-5 w-5" />
                      Create New Knowledge Graph
                    </DialogTitle>
                    <DialogDescription>
                      Create a knowledge graph from documents in your Morphik collection to enhance your queries.
                    </DialogDescription>
                  </DialogHeader>
                  <div className="space-y-4 py-4">
                    <div className="space-y-2">
                      <Label htmlFor="graph-name">Graph Name</Label>
                      <Input
                        id="graph-name"
                        placeholder="Enter a unique name for your graph"
                        value={graphName}
                        onChange={e => setGraphName(e.target.value)}
                      />
                      <p className="text-sm text-muted-foreground">
                        Give your graph a descriptive name that helps you identify its purpose.
                      </p>
                    </div>

                    <div className="border-t pt-4">
                      <h3 className="text-md mb-3 font-medium">Document Selection</h3>
                      <div className="space-y-4">
                        <div className="space-y-2">
                          <Label htmlFor="graph-documents">Document IDs (Optional)</Label>
                          <Textarea
                            id="graph-documents"
                            placeholder="Enter document IDs separated by commas"
                            value={graphDocuments.join(", ")}
                            onChange={e =>
                              setGraphDocuments(
                                e.target.value
                                  .split(",")
                                  .map(id => id.trim())
                                  .filter(id => id)
                              )
                            }
                            className="min-h-[80px]"
                          />
                          <p className="text-xs text-muted-foreground">
                            Specify document IDs to include in the graph, or leave empty and use filters below.
                          </p>
                        </div>

                        <div className="space-y-2">
                          <Label htmlFor="graph-filters">Metadata Filters (Optional)</Label>
                          <Textarea
                            id="graph-filters"
                            placeholder='{"category": "research", "author": "Jane Doe"}'
                            value={graphFilters}
                            onChange={e => setGraphFilters(e.target.value)}
                            className="min-h-[80px] font-mono"
                          />
                          <p className="text-xs text-muted-foreground">
                            JSON object with metadata filters to select documents.
                          </p>
                        </div>
                      </div>
                    </div>
                  </div>
                  <DialogFooter>
                    <Button
                      variant="outline"
                      onClick={() => {
                        setShowCreateDialog(false);
                        setError(null); // Clear error when cancelling
                        // Reset form fields on cancel
                        setGraphName("");
                        setGraphDocuments([]);
                        setGraphFilters("{}");
                      }}
                    >
                      Cancel
                    </Button>
                    <Button
                      onClick={handleCreateGraph} // Removed setShowCreateDialog(false) here, handleCreateGraph does it on success
                      disabled={!graphName || loading}
                    >
                      {loading ? (
                        <div className="mr-2 h-4 w-4 animate-spin rounded-full border-b-2 border-white"></div>
                      ) : null}
                      Create Graph
                    </Button>
                  </DialogFooter>
                </DialogContent>
              </Dialog>
            </div>

            {loading ? (
              <div className="flex items-center justify-center p-8">
                {/* Skeleton Loader for Graph List */}
                <div className="grid w-full grid-cols-2 gap-4 py-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
                  {[...Array(12)].map((_, i) => (
                    <div key={i} className="flex flex-col items-center rounded-md border border-transparent p-2">
                      <Skeleton className="mb-2 h-12 w-12 rounded-md" />
                      <Skeleton className="h-4 w-20 rounded-md" />
                    </div>
                  ))}
                </div>
              </div>
            ) : graphs.length === 0 ? (
              <div className="mt-4 rounded-lg border-2 border-dashed p-8 text-center">
                <Network className="mx-auto mb-3 h-12 w-12 text-muted-foreground" />
                <p className="mb-3 text-muted-foreground">No graphs available.</p>
                <Button onClick={() => setShowCreateDialog(true)} variant="default">
                  <Plus className="mr-2 h-4 w-4" />
                  Create Your First Graph
                </Button>
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-4 py-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
                {graphs.map(graph => (
                  <div
                    key={graph.id}
                    className="group flex cursor-pointer flex-col items-center rounded-md border border-transparent p-2 transition-all hover:border-primary/20 hover:bg-primary/5"
                    onClick={() => handleGraphClick(graph)}
                  >
                    <div className="mb-2 transition-transform group-hover:scale-110">
                      <Network className="h-12 w-12 text-primary/80 group-hover:text-primary" />
                    </div>
                    <span className="w-full max-w-[120px] truncate text-center text-sm font-medium transition-colors group-hover:text-primary">
                      {graph.name}
                    </span>
                    {graph.system_metadata?.status === "processing" && (
                      <Badge
                        variant="secondary"
                        className="mt-1 bg-yellow-400 text-[10px] text-black opacity-90 hover:bg-yellow-400"
                      >
                        Processing
                      </Badge>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Graph Details View */}
        {activeTab === "details" && selectedGraph && (
          <div className="flex flex-col space-y-4">
            {selectedGraph.system_metadata?.status === "processing" && (
              <Alert variant="default" className="mb-2">
                <AlertCircle className="h-4 w-4" />
                <AlertTitle>Graph is processing</AlertTitle>
                <AlertDescription>Entities and relationships are still being extracted.</AlertDescription>
              </Alert>
            )}
            {/* Header with back button */}
            <div className="mb-2 flex items-center justify-between py-2">
              <div className="flex items-center gap-4">
                <Button
                  variant="ghost"
                  size="icon"
                  className="rounded-full hover:bg-muted/50"
                  onClick={() => {
                    setSelectedGraph(null);
                    setActiveTab("list");
                    if (onSelectGraph) {
                      onSelectGraph(undefined);
                    }
                  }}
                >
                  <ArrowLeft size={18} />
                </Button>
                <div className="flex items-center">
                  <Network className="mr-3 h-8 w-8 text-primary" />
                  <h2 className="text-xl font-medium">{selectedGraph.name}</h2>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  onClick={() => setActiveTab("update")}
                  className="flex items-center"
                  disabled={selectedGraph.system_metadata?.status === "processing"}
                >
                  <Plus className="mr-1 h-4 w-4" />
                  Update Graph
                </Button>
                <Button
                  onClick={() => setShowVisualization(true)}
                  className="flex items-center"
                  disabled={selectedGraph.system_metadata?.status === "processing"}
                >
                  <Share2 className="mr-1 h-4 w-4" />
                  Visualize
                </Button>
              </div>
            </div>

            {/* Graph details cards */}
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-4">
              <div className="rounded-lg bg-muted/50 p-4">
                <h4 className="mb-1 text-sm font-medium text-muted-foreground">Documents</h4>
                <div className="text-2xl font-bold">{selectedGraph.document_ids.length}</div>
              </div>

              <div className="rounded-lg bg-muted/50 p-4">
                <h4 className="mb-1 text-sm font-medium text-muted-foreground">Entities</h4>
                <div className="text-2xl font-bold">
                  {selectedGraph.system_metadata?.status === "processing" ? "…" : selectedGraph.entities.length}
                </div>
              </div>

              <div className="rounded-lg bg-muted/50 p-4">
                <h4 className="mb-1 text-sm font-medium text-muted-foreground">Relationships</h4>
                <div className="text-2xl font-bold">
                  {selectedGraph.system_metadata?.status === "processing" ? "…" : selectedGraph.relationships.length}
                </div>
              </div>

              <div className="rounded-lg bg-muted/50 p-4">
                <h4 className="mb-1 text-sm font-medium text-muted-foreground">Created</h4>
                <div className="text-xl font-semibold">{new Date(selectedGraph.created_at).toLocaleDateString()}</div>
                <div className="text-xs text-muted-foreground">
                  {new Date(selectedGraph.created_at).toLocaleTimeString()}
                </div>
              </div>
            </div>

            {/* Entity and Relationship Type summaries */}
            <div className="mt-4 grid grid-cols-1 gap-6 md:grid-cols-2">
              <div>
                <h4 className="mb-2 text-base font-medium">Entity Types</h4>
                <div className="max-h-60 overflow-y-auto rounded-md border bg-muted/30 p-3">
                  {Object.entries(
                    (selectedGraph.system_metadata?.status === "processing" ? [] : selectedGraph.entities).reduce(
                      (acc, entity) => {
                        acc[entity.type] = (acc[entity.type] || 0) + 1;
                        return acc;
                      },
                      {} as Record<string, number>
                    )
                  )
                    .sort(([, countA], [, countB]) => countB - countA) // Sort by count descending
                    .map(([type, count]) => (
                      <div key={type} className="mb-2 flex items-center justify-between text-sm">
                        <div className="flex items-center">
                          <div
                            className="mr-2 h-3 w-3 flex-shrink-0 rounded-full"
                            style={{
                              backgroundColor: entityTypeColors[type.toLowerCase()] || entityTypeColors.default,
                            }}
                          ></div>
                          <span className="truncate" title={type}>
                            {type}
                          </span>
                        </div>
                        <Badge variant="secondary" className="ml-2 flex-shrink-0">
                          {count}
                        </Badge>
                      </div>
                    ))}
                </div>
              </div>

              <div>
                <h4 className="mb-2 text-base font-medium">Relationship Types</h4>
                <div className="max-h-60 overflow-y-auto rounded-md border bg-muted/30 p-3">
                  {Object.entries(
                    (selectedGraph.system_metadata?.status === "processing" ? [] : selectedGraph.relationships).reduce(
                      (acc, rel) => {
                        acc[rel.type] = (acc[rel.type] || 0) + 1;
                        return acc;
                      },
                      {} as Record<string, number>
                    )
                  )
                    .sort(([, countA], [, countB]) => countB - countA) // Sort by count descending
                    .map(([type, count]) => (
                      <div key={type} className="mb-2 flex items-center justify-between text-sm">
                        <span className="truncate" title={type}>
                          {type}
                        </span>
                        <Badge variant="secondary" className="ml-2 flex-shrink-0">
                          {count}
                        </Badge>
                      </div>
                    ))}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Update Graph View */}
        {activeTab === "update" && selectedGraph && (
          <div className="flex flex-col space-y-4">
            {/* Header with back button */}
            <div className="mb-2 flex items-center justify-between py-2">
              <div className="flex items-center gap-4">
                <Button
                  variant="ghost"
                  size="icon"
                  className="rounded-full hover:bg-muted/50"
                  onClick={() => setActiveTab("details")} // Go back to details
                >
                  <ArrowLeft size={18} />
                </Button>
                <div className="flex items-center">
                  <Network className="mr-3 h-8 w-8 text-primary" />
                  <h2 className="text-xl font-medium">Update: {selectedGraph.name}</h2>
                </div>
              </div>
              {/* No buttons needed on the right side for update view */}
            </div>

            <Card>
              <CardHeader>
                <CardTitle className="flex items-center text-lg">
                  {" "}
                  {/* Reduced title size */}
                  {/* <Network className="mr-2 h-5 w-5" />  Removed icon from title */}
                  Add More Data to Graph
                </CardTitle>
                <CardDescription>
                  Expand your knowledge graph by adding new documents based on their IDs or metadata filters.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-6">
                  {" "}
                  {/* Increased spacing */}
                  <div className="rounded-lg border bg-muted/50 p-4">
                    <h4 className="mb-2 text-sm font-medium text-muted-foreground">Current Graph Summary</h4>
                    <div className="grid grid-cols-3 gap-2 text-sm">
                      <div>
                        <span className="font-medium">Docs:</span> {selectedGraph.document_ids.length}
                      </div>
                      <div>
                        <span className="font-medium">Entities:</span> {selectedGraph.entities.length}
                      </div>
                      <div>
                        <span className="font-medium">Rels:</span> {selectedGraph.relationships.length}
                      </div>
                    </div>
                  </div>
                  <div className="space-y-4">
                    <div className="space-y-2">
                      <Label htmlFor="additional-documents">Additional Document IDs</Label>
                      <Textarea
                        id="additional-documents"
                        placeholder="Enter document IDs separated by commas"
                        value={additionalDocuments.join(", ")}
                        onChange={e =>
                          setAdditionalDocuments(
                            e.target.value
                              .split(",")
                              .map(id => id.trim())
                              .filter(id => id)
                          )
                        }
                        className="min-h-[80px]"
                      />
                      <p className="text-xs text-muted-foreground">
                        Specify additional document IDs to include in the graph.
                      </p>
                    </div>

                    <div className="relative flex items-center">
                      <div className="flex-grow border-t border-muted"></div>
                      <span className="mx-4 flex-shrink text-xs uppercase text-muted-foreground">Or</span>
                      <div className="flex-grow border-t border-muted"></div>
                    </div>

                    <div className="space-y-2">
                      <Label htmlFor="additional-filters">Additional Metadata Filters</Label>
                      <Textarea
                        id="additional-filters"
                        placeholder='{"category": "updates"}'
                        value={additionalFilters}
                        onChange={e => setAdditionalFilters(e.target.value)}
                        className="min-h-[80px] font-mono"
                      />
                      <p className="text-xs text-muted-foreground">
                        Use a JSON object with metadata filters to select additional documents.
                      </p>
                    </div>
                  </div>
                  <Button
                    onClick={handleUpdateGraph}
                    disabled={loading || (additionalDocuments.length === 0 && additionalFilters === "{}")} // Disable if no input
                    className="w-full"
                  >
                    {loading ? (
                      <div className="mr-2 h-4 w-4 animate-spin rounded-full border-b-2 border-white"></div>
                    ) : (
                      <Plus className="mr-2 h-4 w-4" />
                    )}
                    Update Knowledge Graph
                  </Button>
                </div>
              </CardContent>
            </Card>
          </div>
        )}
      </div>

      {error && (
        <Alert variant="destructive" className="mt-4">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Error</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
    </div>
  );
};

export default GraphSection;
