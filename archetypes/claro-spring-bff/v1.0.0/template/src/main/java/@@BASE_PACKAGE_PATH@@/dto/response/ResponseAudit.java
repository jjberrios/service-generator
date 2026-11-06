package @@BASE_PACKAGE@@.dto.response;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class ResponseAudit {

    private String code;
    private String detail;
    private String message;
    private String status;
    private String subType;
    private String type;
}