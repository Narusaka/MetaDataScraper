import xml.etree.ElementTree as ET
from typing import Dict, Any, Union, Optional
from xml.dom import minidom
from .schema_nfo import MovieNfo, TvShowNfo, EpisodeNfo


class NfoRenderer:
    @staticmethod
    def _create_element(parent: ET.Element, tag: str, text: Any = None) -> ET.Element:
        """Create XML element with optional text."""
        element = ET.SubElement(parent, tag)
        if text is not None:
            if isinstance(text, str):
                element.text = text
            else:
                element.text = str(text)
        return element

    @staticmethod
    def _create_cdata_element(parent: ET.Element, tag: str, text: str) -> ET.Element:
        """Create XML element with CDATA content."""
        element = ET.SubElement(parent, tag)
        # Manually create CDATA by setting the text with CDATA markers
        # We'll handle the proper CDATA formatting in the final XML output
        element.text = f"CDATA_PLACEHOLDER_{len(text)}_{hash(text)}"
        element.set("cdata_content", text)
        return element

    @staticmethod
    def _add_list_elements(parent: ET.Element, tag: str, items: list) -> None:
        """Add multiple elements for a list."""
        for item in items:
            NfoRenderer._create_element(parent, tag, item)

    @staticmethod
    def _add_combined_credits(parent: ET.Element, credits_list: list) -> None:
        """Add combined credits element."""
        if credits_list:
            combined_credits = ", ".join(credits_list)
            NfoRenderer._create_element(parent, "credits", combined_credits)

    @staticmethod
    def _add_actor_elements(parent: ET.Element, actors: list, media_type: str = "movie") -> None:
        """Add actor elements with name, role, and additional info."""
        for actor in actors:
            if isinstance(actor, dict):
                actor_elem = ET.SubElement(parent, "actor")
                NfoRenderer._create_element(actor_elem, "name", actor.get("name", ""))
                NfoRenderer._create_element(actor_elem, "role", actor.get("role", ""))
                NfoRenderer._create_element(actor_elem, "type", "Actor")  # Add type for Emby compatibility

                # Add original name if available
                if actor.get("originalname"):
                    NfoRenderer._create_element(actor_elem, "originalname", actor["originalname"])

                # Add actor thumb with proper path based on media type
                # Based on Emby community discussions, actor thumbs should use relative paths
                if actor.get("thumb"):
                    thumb_path = actor["thumb"]
                    
                    # Clean up the path for Emby compatibility
                    if thumb_path.startswith("./Season 01/actors/"):
                        # Convert to relative path from episode location to root actors
                        thumb_path = thumb_path.replace("./Season 01/actors/", "../actors/")
                    elif thumb_path.startswith("./actors/"):
                        # For TV episodes, need to go up one level to reach actors directory
                        if media_type == "tv":
                            thumb_path = thumb_path.replace("./actors/", "../actors/")
                        # For movies, keep as is
                    elif thumb_path.startswith("images/actors/"):
                        # Convert from images/actors/ to relative path
                        if media_type == "tv":
                            thumb_path = thumb_path.replace("images/actors/", "../actors/")
                        else:
                            thumb_path = thumb_path.replace("images/actors/", "actors/")
                    elif not "/" in thumb_path:
                        # Assume it's just a filename, add appropriate path
                        if media_type == "tv":
                            thumb_path = f"../actors/{thumb_path}"
                        else:
                            thumb_path = f"actors/{thumb_path}"
                    
                    NfoRenderer._create_element(actor_elem, "thumb", thumb_path)

    @staticmethod
    def _normalize_image_path(image_path: str) -> str:
        """Normalize image path for NFO compatibility."""
        if not image_path:
            return ""

        # If it's already a simple filename, keep it
        if "/" not in image_path and "\\" not in image_path:
            return image_path

        # If it's a TMDB path, convert to simple filename
        if "tmdb.org" in image_path or image_path.startswith("/"):
            # Extract filename from TMDB path
            if "/" in image_path:
                filename = image_path.split("/")[-1]
                # Map to standard names
                if "poster" in filename or "thumb" in image_path.lower():
                    return "poster.jpg"
                elif "backdrop" in filename or "fanart" in image_path.lower():
                    return "fanart.jpg"
                elif "logo" in filename:
                    return "logo.png"
                else:
                    return filename

        return image_path

    @staticmethod
    def render_movie_nfo(nfo: MovieNfo, tmdb_id: Optional[int] = None) -> str:
        """Render MovieNfo to XML string."""
        root = ET.Element("movie")

        NfoRenderer._create_element(root, "title", nfo.title)
        if nfo.originaltitle:
            NfoRenderer._create_element(root, "originaltitle", nfo.originaltitle)
        NfoRenderer._create_element(root, "year", nfo.year)
        if nfo.premiered:
            NfoRenderer._create_element(root, "premiered", nfo.premiered)
        if nfo.plot:
            NfoRenderer._create_cdata_element(root, "plot", nfo.plot)
        if nfo.tagline:
            NfoRenderer._create_element(root, "tagline", nfo.tagline)
        if nfo.runtime:
            NfoRenderer._create_element(root, "runtime", nfo.runtime)
        if nfo.rating:
            NfoRenderer._create_element(root, "rating", nfo.rating)
        if nfo.votes:
            NfoRenderer._create_element(root, "votes", nfo.votes)

        # Add TMDB ID if provided
        if tmdb_id:
            NfoRenderer._create_element(root, "tmdbid", str(tmdb_id))

        NfoRenderer._add_list_elements(root, "genre", nfo.genre)
        NfoRenderer._add_list_elements(root, "country", nfo.country)
        NfoRenderer._add_list_elements(root, "studio", nfo.studio)
        NfoRenderer._add_combined_credits(root, nfo.credits)
        NfoRenderer._add_list_elements(root, "director", nfo.director)
        NfoRenderer._add_actor_elements(root, nfo.actor, "movie")

        # Add network if available (only for TV shows)
        if isinstance(nfo, TvShowNfo) and hasattr(nfo, 'network') and nfo.network:
            NfoRenderer._create_element(root, "network", nfo.network)

        # Add uniqueid for TMDB
        if hasattr(nfo, 'tmdb_id') and nfo.tmdb_id:
            uniqueid_elem = ET.SubElement(root, "uniqueid")
            uniqueid_elem.text = str(nfo.tmdb_id)
            uniqueid_elem.set("type", "tmdb")
            uniqueid_elem.set("default", "true")

        # Use Emby standard image paths (relative to NFO location)
        thumb_path = "poster.jpg"
        fanart_path = "fanart.jpg"

        NfoRenderer._create_element(root, "thumb", thumb_path)
        NfoRenderer._create_element(root, "fanart", fanart_path)

        # Add tags
        for tag in nfo.tags:
            NfoRenderer._create_element(root, "tag", tag)

        # Pretty print XML
        rough_string = ET.tostring(root, encoding='unicode')
        reparsed = minidom.parseString(rough_string)
        xml_string = reparsed.toprettyxml(indent="  ")

        # Replace CDATA placeholders with actual CDATA sections and remove cdata_content attributes
        import re
        lines = xml_string.split('\n')
        new_lines = []

        for line in lines:
            # Remove cdata_content attributes
            line = re.sub(r'\s+cdata_content="[^"]*"', '', line)

            # Replace CDATA placeholders with actual CDATA
            cdata_match = re.search(r'CDATA_PLACEHOLDER_(\d+)_(-?\d+)', line)
            if cdata_match:
                # Find the corresponding element to get the content
                for elem in root.iter():
                    cdata_content = elem.get("cdata_content")
                    if cdata_content:
                        content_len = len(cdata_content)
                        content_hash = hash(cdata_content)
                        if str(content_len) == cdata_match.group(1) and str(content_hash) == cdata_match.group(2):
                            line = line.replace(f'CDATA_PLACEHOLDER_{content_len}_{content_hash}', f'<![CDATA[{cdata_content}]]>')
                            break

            new_lines.append(line)

        return '\n'.join(new_lines)

    @staticmethod
    def render_tvshow_nfo(nfo: TvShowNfo, tmdb_id: Optional[int] = None) -> str:
        """Render TvShowNfo to XML string."""
        root = ET.Element("tvshow")

        NfoRenderer._create_element(root, "title", nfo.title)
        if nfo.originaltitle:
            NfoRenderer._create_element(root, "originaltitle", nfo.originaltitle)
        NfoRenderer._create_element(root, "year", nfo.year)
        if nfo.premiered:
            NfoRenderer._create_element(root, "premiered", nfo.premiered)
        if nfo.plot:
            NfoRenderer._create_cdata_element(root, "plot", nfo.plot)
        if nfo.tagline:
            NfoRenderer._create_element(root, "tagline", nfo.tagline)
        if nfo.runtime:
            NfoRenderer._create_element(root, "runtime", nfo.runtime)
        if nfo.rating:
            NfoRenderer._create_element(root, "rating", nfo.rating)
        if nfo.votes:
            NfoRenderer._create_element(root, "votes", nfo.votes)

        # Add TMDB ID if provided
        if tmdb_id:
            NfoRenderer._create_element(root, "tmdbid", str(tmdb_id))

        NfoRenderer._add_list_elements(root, "genre", nfo.genre)
        NfoRenderer._add_list_elements(root, "country", nfo.country)
        NfoRenderer._add_list_elements(root, "studio", nfo.studio)
        NfoRenderer._add_combined_credits(root, nfo.credits)
        NfoRenderer._add_list_elements(root, "director", nfo.director)
        NfoRenderer._add_actor_elements(root, nfo.actor, "tv")

        # Add all networks (for TV shows)
        if hasattr(nfo, 'networks') and nfo.networks:
            for network in nfo.networks:
                NfoRenderer._create_element(root, "network", network)
        elif hasattr(nfo, 'network') and nfo.network:
            # Fallback to single network
            NfoRenderer._create_element(root, "network", nfo.network)

        # Add status for TV shows
        if hasattr(nfo, 'status') and nfo.status:
            NfoRenderer._create_element(root, "status", nfo.status)

        # Add homepage
        if hasattr(nfo, 'homepage') and nfo.homepage:
            NfoRenderer._create_element(root, "homepage", nfo.homepage)

        # Add uniqueid for TMDB
        if hasattr(nfo, 'tmdb_id') and nfo.tmdb_id:
            uniqueid_elem = ET.SubElement(root, "uniqueid")
            uniqueid_elem.text = str(nfo.tmdb_id)
            uniqueid_elem.set("type", "tmdb")
            uniqueid_elem.set("default", "true")

        # Use Emby standard image paths (relative to NFO location)
        thumb_path = "poster.jpg"
        fanart_path = "fanart.jpg"

        NfoRenderer._create_element(root, "thumb", thumb_path)
        NfoRenderer._create_element(root, "fanart", fanart_path)

        # Add tags
        for tag in nfo.tags:
            NfoRenderer._create_element(root, "tag", tag)

        # Pretty print XML and fix CDATA
        rough_string = ET.tostring(root, encoding='unicode')
        reparsed = minidom.parseString(rough_string)
        xml_string = reparsed.toprettyxml(indent="  ")

        # Replace CDATA placeholders with actual CDATA sections and remove cdata_content attributes
        import re
        lines = xml_string.split('\n')
        new_lines = []

        for line in lines:
            # Remove cdata_content attributes
            line = re.sub(r'\s+cdata_content="[^"]*"', '', line)

            # Replace CDATA placeholders with actual CDATA
            cdata_match = re.search(r'CDATA_PLACEHOLDER_(\d+)_(-?\d+)', line)
            if cdata_match:
                # Find the corresponding element to get the content
                for elem in root.iter():
                    cdata_content = elem.get("cdata_content")
                    if cdata_content:
                        content_len = len(cdata_content)
                        content_hash = hash(cdata_content)
                        if str(content_len) == cdata_match.group(1) and str(content_hash) == cdata_match.group(2):
                            line = line.replace(f'CDATA_PLACEHOLDER_{content_len}_{content_hash}', f'<![CDATA[{cdata_content}]]>')
                            break

            new_lines.append(line)

        return '\n'.join(new_lines)

    @staticmethod
    def render_episode_nfo(nfo: EpisodeNfo) -> str:
        """Render EpisodeNfo to XML string using episodedetails format."""
        root = ET.Element("episodedetails")

        NfoRenderer._create_element(root, "title", nfo.title)
        if nfo.originaltitle:
            NfoRenderer._create_element(root, "originaltitle", nfo.originaltitle)
        if nfo.sorttitle:
            NfoRenderer._create_element(root, "sorttitle", nfo.sorttitle)
        NfoRenderer._create_element(root, "year", nfo.year)
        if nfo.premiered:
            NfoRenderer._create_element(root, "premiered", nfo.premiered)
            NfoRenderer._create_element(root, "aired", nfo.premiered)  # Add aired field for episodes
        if nfo.runtime:
            NfoRenderer._create_element(root, "runtime", nfo.runtime)
        if nfo.plot:
            NfoRenderer._create_cdata_element(root, "plot", nfo.plot)
        if nfo.outline:
            NfoRenderer._create_cdata_element(root, "outline", nfo.outline)
        if nfo.rating:
            NfoRenderer._create_element(root, "rating", nfo.rating)
        if nfo.votes:
            NfoRenderer._create_element(root, "votes", nfo.votes)
        if nfo.mpaa:
            NfoRenderer._create_element(root, "mpaa", nfo.mpaa)

        NfoRenderer._add_list_elements(root, "genre", nfo.genre)
        NfoRenderer._add_list_elements(root, "country", nfo.country)
        NfoRenderer._add_list_elements(root, "studio", nfo.studio)
        if nfo.label:
            NfoRenderer._create_element(root, "label", nfo.label)
        NfoRenderer._add_list_elements(root, "credits", nfo.credits)
        NfoRenderer._add_list_elements(root, "director", nfo.director)
        NfoRenderer._add_actor_elements(root, nfo.actor, "tv")  # Episodes are part of TV shows

        # Add lockedfields
        NfoRenderer._create_element(root, "lockedfields", nfo.lockedfields or "Name")

        # Add set information
        if nfo.set:
            set_elem = ET.SubElement(root, "set")
            if nfo.set.get("name"):
                NfoRenderer._create_element(set_elem, "name", nfo.set["name"])
            if nfo.set.get("overview"):
                NfoRenderer._create_cdata_element(set_elem, "overview", nfo.set["overview"])

        # Add tags
        for tag in nfo.tags:
            NfoRenderer._create_element(root, "tag", tag)

        # Use Emby standard episode image paths
        # Based on Emby community feedback, use relative paths for episode images
        if nfo.thumb:
            # Use the episode-specific thumb file
            NfoRenderer._create_element(root, "thumb", nfo.thumb)
        
        # For fanart, use episode-specific fanart if available, otherwise point to main fanart
        if nfo.fanart:
            NfoRenderer._create_element(root, "fanart", nfo.fanart)
        else:
            # Fallback to main fanart in parent directory
            NfoRenderer._create_element(root, "fanart", "../fanart.jpg")

        if nfo.num:
            NfoRenderer._create_element(root, "num", nfo.num)
        if nfo.website:
            NfoRenderer._create_element(root, "website", nfo.website)

        # Pretty print XML and fix CDATA
        rough_string = ET.tostring(root, encoding='unicode')
        reparsed = minidom.parseString(rough_string)
        xml_string = reparsed.toprettyxml(indent="  ")

        # Replace CDATA placeholders with actual CDATA sections and remove cdata_content attributes
        import re
        lines = xml_string.split('\n')
        new_lines = []

        for line in lines:
            # Remove cdata_content attributes
            line = re.sub(r'\s+cdata_content="[^"]*"', '', line)

            # Replace CDATA placeholders with actual CDATA
            cdata_match = re.search(r'CDATA_PLACEHOLDER_(\d+)_(-?\d+)', line)
            if cdata_match:
                # Find the corresponding element to get the content
                for elem in root.iter():
                    cdata_content = elem.get("cdata_content")
                    if cdata_content:
                        content_len = len(cdata_content)
                        content_hash = hash(cdata_content)
                        if str(content_len) == cdata_match.group(1) and str(content_hash) == cdata_match.group(2):
                            line = line.replace(f'CDATA_PLACEHOLDER_{content_len}_{content_hash}', f'<![CDATA[{cdata_content}]]>')
                            break

            new_lines.append(line)

        return '\n'.join(new_lines)
