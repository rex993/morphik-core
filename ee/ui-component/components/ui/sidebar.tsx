"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  FileText,
  Search,
  MessageSquare,
  ChevronLeft,
  ChevronRight,
  Network,
  Copy,
  Check,
  ArrowLeft,
  Bot,
  PlugZap,
} from "lucide-react";
import { ModeToggle } from "@/components/mode-toggle";
import { Input } from "@/components/ui/input";

// Define the specific section types the Sidebar expects
export type SidebarSectionType = "documents" | "search" | "chat" | "graphs" | "agent" | "connections";

interface SidebarProps extends React.HTMLAttributes<HTMLDivElement> {
  activeSection: SidebarSectionType; // Use the specific type
  onSectionChange: (section: SidebarSectionType) => void; // Use the specific type
  connectionUri?: string;
  isReadOnlyUri?: boolean;
  onUriChange?: (uri: string) => void;
  isCollapsed?: boolean;
  setIsCollapsed?: (collapsed: boolean) => void;
  onBackClick?: () => void;
}

export function Sidebar({
  className,
  activeSection,
  onSectionChange,
  connectionUri,
  isReadOnlyUri = false,
  onUriChange,
  isCollapsed: externalIsCollapsed,
  setIsCollapsed: externalSetIsCollapsed,
  onBackClick,
  ...props
}: SidebarProps) {
  // Use internal state that syncs with external state if provided
  const [internalIsCollapsed, setInternalIsCollapsed] = React.useState(false);
  const [editableUri, setEditableUri] = React.useState("");
  const [isEditingUri, setIsEditingUri] = React.useState(false);

  // Determine if sidebar is collapsed based on props or internal state
  const isCollapsed = externalIsCollapsed !== undefined ? externalIsCollapsed : internalIsCollapsed;

  // Toggle function that updates both internal and external state if provided
  const toggleCollapsed = () => {
    if (externalSetIsCollapsed) {
      externalSetIsCollapsed(!isCollapsed);
    }
    setInternalIsCollapsed(!isCollapsed);
  };

  // Initialize from localStorage or props
  React.useEffect(() => {
    // For development/testing - check if we have a stored URI
    const storedUri = typeof window !== "undefined" ? localStorage.getItem("morphik_uri") : null;

    if (storedUri) {
      setEditableUri(storedUri);
      // Note: we're removing the auto-notification to avoid refresh loops
    } else if (connectionUri) {
      setEditableUri(connectionUri);
    }
  }, [connectionUri]);

  // Update editable URI when connectionUri changes
  React.useEffect(() => {
    if (connectionUri && connectionUri !== editableUri) {
      setEditableUri(connectionUri);
    }
  }, [connectionUri, editableUri]);

  // Extract connection details if URI is provided
  const isConnected = !!connectionUri;
  let connectionHost = null;
  try {
    if (connectionUri) {
      // Try to extract host from morphik:// format
      const match = connectionUri.match(/^morphik:\/\/[^@]+@(.+)/);
      if (match && match[1]) {
        connectionHost = match[1];
        // If it includes a protocol, remove it to get just the host
        if (connectionHost.includes("://")) {
          connectionHost = new URL(connectionHost).host;
        }
      }
    }
  } catch (error) {
    console.error("Error parsing connection URI:", error);
    connectionHost = "localhost";
  }

  // Handle saving the connection URI
  const handleSaveUri = () => {
    // Store the URI in localStorage for persistence
    if (typeof window !== "undefined") {
      if (editableUri.trim() === "") {
        // If URI is empty, remove from localStorage to default to local
        localStorage.removeItem("morphik_uri");
      } else {
        localStorage.setItem("morphik_uri", editableUri);
      }
    }

    // Call the onUriChange callback if provided
    if (onUriChange) {
      // Pass empty string to trigger default localhost connection
      onUriChange(editableUri.trim());
    } else {
      // Fallback for demo purposes if no callback is provided
      console.log("New URI:", editableUri || "(empty - using localhost)");
    }

    // Close editing mode
    setIsEditingUri(false);
  };

  return (
    <div
      className={cn(
        "relative flex flex-col border-r bg-background transition-all duration-300",
        isCollapsed ? "w-16" : "w-64",
        className
      )}
      {...props}
    >
      <div className="flex flex-col border-b">
        <div className="flex items-center justify-between p-4">
          {!isCollapsed && <h2 className="text-lg font-semibold">Morphik</h2>}
          <Button variant="ghost" size="icon" className="ml-auto" onClick={toggleCollapsed}>
            {isCollapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
          </Button>
        </div>

        {/* Display connection information when not collapsed */}
        {!isCollapsed && (
          <div className="px-4 pb-3">
            <div className="rounded-md bg-muted p-2 text-xs">
              <div className="mb-1 font-medium">{isConnected ? "Connected to:" : "Connection Status:"}</div>
              <div className="text-muted-foreground">
                {isConnected &&
                connectionHost &&
                !connectionHost.includes("localhost") &&
                !connectionHost.includes("local") ? (
                  <span className="truncate">{connectionHost}</span>
                ) : (
                  <span className="flex items-center">
                    <span className="mr-1.5 h-2 w-2 rounded-full bg-green-500"></span>
                    Local Connection (localhost:8000)
                  </span>
                )}
              </div>

              {/* Connection URI Section */}
              <div className="mt-2 flex flex-col border-t border-background pt-2">
                <div className="flex items-center justify-between">
                  <div className="font-medium">Connection URI:</div>
                  {isConnected && !isEditingUri && (
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-6 w-6"
                      onClick={() => {
                        if (connectionUri) {
                          navigator.clipboard.writeText(connectionUri);
                          // Use the showAlert helper instead of native alert
                          const event = new CustomEvent("morphik:alert", {
                            detail: {
                              type: "success",
                              title: "Copied!",
                              message: "Connection URI copied to clipboard",
                              duration: 3000,
                            },
                          });
                          window.dispatchEvent(event);
                        }
                      }}
                      title="Copy connection URI"
                    >
                      <Copy className="h-3.5 w-3.5" />
                    </Button>
                  )}

                  {/* Add Edit button if not editing and not in read-only mode */}
                  {!isReadOnlyUri && !isEditingUri && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-6 px-2 py-0.5 text-xs"
                      onClick={() => setIsEditingUri(true)}
                    >
                      {connectionUri ? "Edit" : "Add URI"}
                    </Button>
                  )}
                </div>

                {/* URI Display or Editing Area */}
                {isReadOnlyUri ? (
                  // Read-only display for production/cloud environments
                  <div className="mt-1 break-all rounded bg-background p-1 font-mono text-xs">
                    {connectionUri
                      ? // Show first and last characters with asterisks in between
                        `${connectionUri.substring(0, 12)}...${connectionUri.substring(connectionUri.length - 12)}`
                      : "No URI configured"}
                  </div>
                ) : isEditingUri ? (
                  // Editing mode (only available when not read-only)
                  <div className="mt-1">
                    <div className="flex items-center gap-1">
                      <Input
                        value={editableUri}
                        onChange={e => setEditableUri(e.target.value)}
                        placeholder="morphik://token@host (empty for localhost)"
                        className="h-7 font-mono text-xs"
                      />
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        onClick={() => {
                          setEditableUri("");
                          handleSaveUri();
                        }}
                        title="Clear URI (use localhost)"
                      >
                        <span className="text-xs">X</span>
                      </Button>
                      <Button variant="ghost" size="icon" className="h-7 w-7" onClick={handleSaveUri} title="Save URI">
                        <Check className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                    <div className="mt-0.5 text-[10px] text-muted-foreground">
                      Format: morphik://your_token@your_api_host
                    </div>
                  </div>
                ) : (
                  // Display current URI (or placeholder)
                  <div className="mt-1 break-all rounded bg-background p-1 font-mono text-xs">
                    {connectionUri || "Using localhost by default - click Edit to change"}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Navigation Items */}
      <ScrollArea className="flex-1 px-2 py-4">
        <div className={cn("flex flex-col space-y-1", isCollapsed ? "items-center" : "")}>
          <Button
            variant={activeSection === "documents" ? "secondary" : "ghost"}
            className={cn("w-full justify-start", isCollapsed && "justify-center")}
            onClick={() => onSectionChange("documents")}
            title="Documents"
          >
            <FileText className={cn("h-5 w-5", !isCollapsed && "mr-2")} />
            {!isCollapsed && <span>Documents</span>}
          </Button>
          <Button
            variant={activeSection === "search" ? "secondary" : "ghost"}
            className={cn("w-full justify-start", isCollapsed && "justify-center")}
            onClick={() => onSectionChange("search")}
            title="Search"
          >
            <Search className={cn("h-5 w-5", !isCollapsed && "mr-2")} />
            {!isCollapsed && <span>Search</span>}
          </Button>
          <Button
            variant={activeSection === "chat" ? "secondary" : "ghost"}
            className={cn("w-full justify-start", isCollapsed && "justify-center")}
            onClick={() => onSectionChange("chat")}
            title="Chat"
          >
            <MessageSquare className={cn("h-5 w-5", !isCollapsed && "mr-2")} />
            {!isCollapsed && <span>Chat</span>}
          </Button>
          <Button
            variant={activeSection === "graphs" ? "secondary" : "ghost"}
            className={cn("w-full justify-start", isCollapsed && "justify-center")}
            onClick={() => onSectionChange("graphs")}
            title="Graphs"
          >
            <Network className={cn("h-5 w-5", !isCollapsed && "mr-2")} />
            {!isCollapsed && <span>Graphs</span>}
          </Button>
          <Button
            variant={activeSection === "agent" ? "secondary" : "ghost"}
            className={cn("w-full justify-start", isCollapsed && "justify-center")}
            onClick={() => onSectionChange("agent")}
            title="Agent"
          >
            <Bot className={cn("h-5 w-5", !isCollapsed && "mr-2")} />
            {!isCollapsed && <span>Agent</span>}
          </Button>
          {/* New Connections Nav Item */}
          <Button
            variant={activeSection === "connections" ? "secondary" : "ghost"}
            className={cn("w-full justify-start", isCollapsed && "justify-center")}
            onClick={() => onSectionChange("connections")}
            title="Connections"
          >
            <PlugZap className={cn("h-5 w-5", !isCollapsed && "mr-2")} />
            {!isCollapsed && <span>Connections</span>}
          </Button>
        </div>
      </ScrollArea>

      <div
        className={cn("border-t p-4", isCollapsed ? "flex justify-center" : "flex items-center justify-between gap-2")}
      >
        {!isCollapsed && onBackClick && (
          <Button variant="ghost" size="sm" onClick={onBackClick} className="flex items-center gap-2">
            <ArrowLeft className="h-4 w-4" />
            <span>Back to dashboard</span>
          </Button>
        )}
        <ModeToggle />
      </div>
    </div>
  );
}
